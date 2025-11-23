"""Config data package - contains plans and other configuration data files."""
from .plans import PLAN_FEATURES, PLAN_PRICING, get_plan_feature, has_feature, get_feature_limit

__all__ = ['PLAN_FEATURES', 'PLAN_PRICING', 'get_plan_feature', 'has_feature', 'get_feature_limit']



