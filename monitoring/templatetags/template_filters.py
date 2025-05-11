# monitoring/templatetags/template_filters.py
from django import template
import datetime

register = template.Library()

@register.filter
def mul(value, arg):
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError):
        return None

@register.filter
def div(value, arg):
    try:
        return float(value) / float(arg)
    except (ValueError, TypeError, ZeroDivisionError):
        return None

@register.filter
def sub(value, arg):
    try:
        return float(value) - float(arg)
    except (ValueError, TypeError, ZeroDivisionError):
        return None

@register.filter
def format_timedelta(value):
    """Format a timedelta object into a readable string"""
    if not isinstance(value, datetime.timedelta):
        return value

    days = value.days
    hours, remainder = divmod(value.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    result = ""
    if days:
        result += f"{days} {'дн.' if days != 1 else 'день'} "
    if hours:
        result += f"{hours} {'год.' if hours != 1 else 'година'} "
    if minutes:
        result += f"{minutes} {'хв.' if minutes != 1 else 'хвилина'} "
    if seconds and not (days or hours):
        result += f"{seconds} {'сек.' if seconds != 1 else 'секунда'}"

    return result.strip() or "Менше хвилини"