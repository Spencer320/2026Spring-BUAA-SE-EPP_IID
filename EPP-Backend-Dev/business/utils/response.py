from django.http import JsonResponse


def json_response_wrapper(status: int):
    def inner(data: dict | None = None, msg: str = "", err: str = "") -> JsonResponse:
        if data is None:
            data = dict()
        if "message" not in data and msg != "":
            data["message"] = msg
        if "error" not in data and err != "":
            data["error"] = err
        return JsonResponse(data=data, status=status)

    return inner


ok = json_response_wrapper(200)
fail = json_response_wrapper(400)
unauthorized = json_response_wrapper(401)
