from typing import Dict, Any, List, Callable, Hashable

from typing_extensions import TypeVar

_Ty1 = TypeVar("_Ty1")


def truncate_dict_keys(
    origin: Dict[_Ty1, Any], allowed_keys: List[_Ty1]
) -> Dict[_Ty1, Any]:
    """
    Truncate the keys of a dictionary to only include the allowed keys.

    Args:
        origin (Dict[_Ty1, Any]): The original dictionary.
        allowed_keys (List[_Ty1]): The list of allowed keys.

    Returns:
        Dict[_Ty1, Any]: A new dictionary with only the allowed keys.
    """
    return {key: value for key, value in origin.items() if key in allowed_keys}


def unique_list(lst: List[_Ty1], key: Callable[[_Ty1], Hashable] = None) -> List[_Ty1]:
    """
    Remove duplicates from a list while preserving the order.

    Args:
        lst (List[_Ty1]): The original list.
        key (Callable[[_Ty1], Hashable]): A function that takes an element and returns a hashable key.

    Returns:
        List[_Ty1]: A new list with unique elements.
    """
    if key is None:
        key = lambda x: x
    seen = set()
    return [x for x in lst if not (key(x) in seen or seen.add(key(x)))]
