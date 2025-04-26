# monitoring/templatetags/template_filters.py
from django import template

register = template.Library()

@register.filter
def mul(value, arg):
    """Множить значення на аргумент"""
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError):
        return None

@register.filter
def div(value, arg):
    """Ділить значення на аргумент"""
    try:
        return float(value) / float(arg)
    except (ValueError, TypeError, ZeroDivisionError):
        return None

@register.filter
def sub(value, arg):
    """Ділить значення на аргумент"""
    try:
        return float(value) - float(arg)
    except (ValueError, TypeError, ZeroDivisionError):
        return None

