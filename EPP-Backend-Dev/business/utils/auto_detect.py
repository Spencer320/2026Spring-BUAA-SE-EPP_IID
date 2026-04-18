import uuid

from business.models.detectable import Detectable

from business.utils.text_censor import text_censor


def detect_content_safety(content: str, obj: Detectable):
    idd = uuid.uuid4()
    print(f"[{idd}] Detecting content: {content} for {obj.pk}")
    try:
        results = text_censor(content)
    except Exception as e:
        print(f"[{idd}] Error during text censoring: {e}")
        results = {
            "conclusion": "合规",
        }
    if results.get("conclusion", "合规") != "合规":
        reasons = set()
        for result in results.get("data", []):
            if result.get("conclusion", "合规") != "合规":
                reasons.add(result.get("msg", "位置原因"))
        obj.block()
        obj.insert_auto_delete(
            reason="、".join(reasons),
            title=f"您的 {obj.get_content_name()} 已被自动删除",
        )
        print(f"[{idd}] Content blocked")
    else:
        obj.safe()
        print(f"[{idd}] Content is safe")
