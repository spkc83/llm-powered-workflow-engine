"""Typed application service for every consequential operation in the catalog."""

from typing import Annotated, Any, Literal, Protocol

from pydantic import BaseModel, Field

from workflow_engine.auth.models import Permission
from workflow_engine.core.gateway import ActionGateway
from workflow_engine.core.kernel import (
    ActionCommand,
    ActionRecord,
    CaseKernel,
    FactAuthority,
    FactProposal,
)


class IssueRefundPayload(BaseModel):
    action: Literal["issue_refund"]
    order_id: str
    customer_id: str
    refund_amount: float = Field(gt=0)
    currency: str = "USD"
    payment_method: str
    reason: str


class StoreCreditPayload(BaseModel):
    action: Literal["issue_store_credit"]
    order_id: str
    customer_id: str
    amount: float = Field(gt=0)
    currency: str = "USD"
    reason: str


class CaseStatusPayload(BaseModel):
    action: Literal["update_case_status"]
    target_status: str
    reason: str


class EftDisputePayload(BaseModel):
    action: Literal["file_eft_dispute"]
    customer_id: str
    transaction_id: str
    amount: float = Field(gt=0)
    dispute_type: Literal["unauthorized", "error", "fraud"]


class ProvisionalCreditPayload(BaseModel):
    action: Literal["issue_provisional_credit"]
    customer_id: str
    dispute_id: str
    amount: float = Field(gt=0)


class EscalationPayload(BaseModel):
    action: Literal["escalate_to_supervisor"]
    reason: str
    priority: Literal["low", "normal", "high", "urgent"] = "normal"


class CaseNotePayload(BaseModel):
    action: Literal["add_case_note"]
    note: str = Field(min_length=1, max_length=10000)


class AccountRestrictionPayload(BaseModel):
    action: Literal["flag_account"]
    account_id: str
    reason: str
    restriction: Literal["monitor", "restrict", "freeze"]


class SarPayload(BaseModel):
    action: Literal["submit_sar"]
    account_id: str
    alert_id: str
    narrative_ref: str = Field(
        description="Secure reference to the SAR narrative; narrative text is not accepted here"
    )


class CloseAlertPayload(BaseModel):
    action: Literal["close_alert"]
    alert_id: str
    resolution: Literal["confirmed_fraud", "false_positive", "escalated"]


ActionPayload = Annotated[
    IssueRefundPayload
    | StoreCreditPayload
    | CaseStatusPayload
    | EftDisputePayload
    | ProvisionalCreditPayload
    | EscalationPayload
    | CaseNotePayload
    | AccountRestrictionPayload
    | SarPayload
    | CloseAlertPayload,
    Field(discriminator="action"),
]


class AuthoritativeResourceRef(BaseModel):
    resource_type: str
    resource_id: str


class ConsequentialActionRequest(BaseModel):
    case_id: str
    customer_id: str
    procedure_id: str
    procedure_version: str
    policy_package_id: str
    idempotency_key: str = Field(min_length=4, max_length=300)
    resource: AuthoritativeResourceRef | None = None
    payload: ActionPayload
    consent_evidence_ref: str | None = None
    approval_evidence_ref: str | None = None
    connector_binding_id: str | None = None
    connector_binding_version: str | None = None
    contract_version: str | None = None

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "case_id": "CASE-STORE-CREDIT-001",
                    "customer_id": "CUST-456",
                    "procedure_id": "cs_refund",
                    "procedure_version": "1.0.0",
                    "policy_package_id": "refund@1.0.0:NAM",
                    "idempotency_key": "store-credit:ORD-123",
                    "resource": {"resource_type": "order", "resource_id": "ORD-123"},
                    "payload": {
                        "action": "issue_store_credit",
                        "order_id": "ORD-123",
                        "customer_id": "CUST-456",
                        "amount": 79.99,
                        "currency": "USD",
                        "reason": "outside refund window",
                    },
                    "consent_evidence_ref": "chat-message:consent-42",
                }
            ]
        }
    }


ACTION_PERMISSIONS: dict[str, Permission] = {
    "issue_refund": Permission.REFUND_WRITE,
    "issue_store_credit": Permission.REFUND_WRITE,
    "update_case_status": Permission.CASE_WRITE,
    "file_eft_dispute": Permission.CASE_WRITE,
    "issue_provisional_credit": Permission.REFUND_WRITE,
    "escalate_to_supervisor": Permission.ESCALATION_CREATE,
    "add_case_note": Permission.CASE_WRITE,
    "flag_account": Permission.ACCOUNT_FLAG,
    "submit_sar": Permission.SAR_SUBMIT,
    "close_alert": Permission.FRAUD_ALERT_WRITE,
}


class AuthoritativeResourceProvider(Protocol):
    async def get_resource(
        self, resource_type: str, resource_id: str
    ) -> dict[str, Any] | None: ...


class ConsequentialActionService:
    def __init__(
        self,
        kernel: CaseKernel,
        gateway: ActionGateway,
        resources: AuthoritativeResourceProvider,
    ):
        self.kernel = kernel
        self.gateway = gateway
        self.resources = resources

    async def submit(
        self, request: ConsequentialActionRequest, *, actor_id: str
    ) -> ActionRecord:
        duplicate = await self.kernel.store.get_action_by_key(request.idempotency_key)
        if duplicate:
            requested_parameters = request.payload.model_dump(
                exclude={"action"}, mode="json"
            )
            duplicate_parameters = duplicate.command.parameters
            if request.payload.action == "issue_refund":
                # v3.1 refund commands predate explicit currency/payment-method
                # fields. Their existing effect remains the idempotent authority;
                # compare every field that was originally bound rather than
                # rejecting a safe schema enrichment during upgrade.
                parameters_match = all(
                    requested_parameters.get(name) == value
                    for name, value in duplicate_parameters.items()
                )
            else:
                parameters_match = duplicate_parameters == requested_parameters
            if (
                duplicate.command.case_id != request.case_id
                or duplicate.command.action != request.payload.action
                or duplicate.command.policy_package_id != request.policy_package_id
                or not parameters_match
            ):
                raise ValueError(
                    "Idempotency key is already bound to a different action request"
                )
            case = await self.kernel.store.get_case(duplicate.command.case_id)
            if case is None or case.customer_id != request.customer_id:
                raise ValueError("Idempotent action does not belong to this customer")
            return await self.gateway.dispatch(duplicate)

        action = request.payload.action
        parameters = request.payload.model_dump(exclude={"action"}, mode="json")
        from workflow_engine.core.action_specs import ACTION_SPECIFICATIONS

        specification = ACTION_SPECIFICATIONS[action]
        authoritative = specification.authoritative_parameters
        fact_refs: dict[str, str] = {}
        authorities: dict[str, FactAuthority] = {}
        evidence_ref: str | None = None
        upstream_payload: dict[str, Any] = {}
        if authoritative:
            if request.resource is None:
                raise ValueError("This action requires an authoritative resource reference")
            resource = await self.resources.get_resource(
                request.resource.resource_type, request.resource.resource_id
            )
            if resource is None:
                raise ValueError("Authoritative resource was not found")
            upstream_payload = self._normalize_resource_payload(action, resource["payload"])
            binding = specification.customer_binding_parameter
            if binding is not None:
                if binding not in upstream_payload:
                    raise ValueError(
                        f"Authoritative resource is missing customer binding {binding}"
                    )
                if str(upstream_payload[binding]) != request.customer_id:
                    raise ValueError(
                        "Authoritative resource does not belong to the serviced customer"
                    )
            evidence_ref = (
                f"sandbox:{request.resource.resource_type}:{request.resource.resource_id}:"
                f"v{resource['version']}"
            )
            for parameter in authoritative:
                if parameter not in upstream_payload:
                    raise ValueError(f"Authoritative resource is missing {parameter}")
                if upstream_payload[parameter] != parameters.get(parameter):
                    raise ValueError(
                        f"Parameter {parameter} does not match the authoritative resource"
                    )

        case = await self.kernel.store.get_case(request.case_id)
        if case is None:
            case = await self.kernel.create_case(
                request.case_id,
                request.customer_id,
                request.procedure_id,
                request.procedure_version,
            )
        elif case.customer_id != request.customer_id:
            raise ValueError("Case customer does not match authenticated customer")
        elif case.procedure_version != request.procedure_version:
            raise ValueError("Active cases cannot silently switch procedure versions")

        for parameter in sorted(authoritative):
            fact_name = f"{action}.{parameter}"
            case = await self.kernel.commit_fact(
                request.case_id,
                FactProposal(
                    name=fact_name,
                    value=upstream_payload[parameter],
                    authority=FactAuthority.VERIFIED,
                    source="authoritative_resource_adapter",
                    evidence_ref=evidence_ref or "",
                ),
                case.version,
            )
            fact_refs[parameter] = fact_name
            authorities[parameter] = FactAuthority.VERIFIED

        command = ActionCommand(
            action=action,
            case_id=request.case_id,
            policy_package_id=request.policy_package_id,
            actor_id=actor_id,
            idempotency_key=request.idempotency_key,
            parameters=parameters,
            parameter_fact_refs=fact_refs,
            required_fact_authority=authorities,
            consent_evidence_ref=request.consent_evidence_ref,
            approval_evidence_ref=request.approval_evidence_ref,
            connector_binding_id=request.connector_binding_id,
            connector_binding_version=request.connector_binding_version,
            contract_version=request.contract_version,
        )
        authorized = await self.gateway.authorize(command, case.version)
        return await self.gateway.dispatch(authorized)

    @staticmethod
    def _normalize_resource_payload(
        action: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        normalized = dict(payload)
        if action == "issue_refund":
            if "refund_amount" not in normalized and "amount" in normalized:
                normalized["refund_amount"] = normalized["amount"]
        if action in {"issue_refund", "issue_store_credit"} and "currency" not in normalized:
            normalized["currency"] = "USD"
        return normalized
