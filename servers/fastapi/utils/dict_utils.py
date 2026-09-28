


def deep_update(original: dict, updates: dict) -> dict:
    for key, value in updates.items():
        if key in original:
            if isinstance(original[key], dict) and isinstance(value, dict):
                deep_update(original[key], value)
            elif isinstance(original[key], list) and isinstance(value, list):
                if len(value) == 0:
                    continue
                elif len(value) == 1 and isinstance(value[0], dict):
                    if len(original[key]) > 0 and isinstance(original[key][0], dict):
                        deep_update(original[key][0], value[0])
                    else:
                        original[key][0] = (
                            value[0] if len(original[key]) > 0 else value[0]
                        )
                else:
                    min_length = min(len(original[key]), len(value))
                    for i in range(min_length):
                        if isinstance(original[key][i], dict) and isinstance(
                            value[i], dict
                        ):
                            deep_update(original[key][i], value[i])
                        else:
                            original[key][i] = value[i]
            elif not isinstance(value, (dict, list)):
                original[key] = value
        else:
            if not isinstance(value, (dict, list)):
                original[key] = value
    return original


def has_more_than_n_keys(obj: dict[str, object], n: int) -> bool:
    i = 0
    for _ in obj.keys():
        i += 1
        if i > n:
            return True
    return False
