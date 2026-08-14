from app.ai.base import AIProvider
from app.config import RECOMMENDATION_DEFAULT_COUNT, RECOMMENDATION_MAX_COUNT
from app.conversation.models import ConversationContext, ConversationPlan


class ConversationPlanner:
    def __init__(self, ai: AIProvider) -> None:
        self.ai = ai

    def plan(self, message: str, context: ConversationContext) -> ConversationPlan:
        plan = self.ai.create_plan(message, context)
        if not plan.reference_product_code:
            plan.reference_product_code = context.latest_product_code
        if plan.requested_count < 1:
            plan.requested_count = RECOMMENDATION_DEFAULT_COUNT
        plan.requested_count = min(plan.requested_count, RECOMMENDATION_MAX_COUNT)
        return plan
