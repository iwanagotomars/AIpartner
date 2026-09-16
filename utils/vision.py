import base64
import re
from io import BytesIO
from difflib import SequenceMatcher
from PIL import Image, ImageOps


def image_to_data_url(
    image_path: str | BytesIO,
    max_long_edge: int = 1536,
    convert_png_to_jpeg: bool = True,
    jpeg_quality: int = 90,
) -> str:
    """
    读取本地图片 → 尺寸压缩 → 转换为JPEG → 转换为Base64 Data URL。

    Args:
        image_path (str | BytesIO):
            本地图片文件路径，或存档处理复用的内存文件。
        max_long_edge (int, optional):
            输出图片允许的最大长边像素值。
            如果原图的宽或高超过该值，会保持宽高比等比例缩小。
            值为None的话就不进行缩小。
        convert_png_to_jpeg (bool, optional):
            是否将 PNG 图片转换为 JPEG。默认值为 True。
            值为False时会保留输入的PNG图片的格式。
        jpeg_quality (int, optional):
            JPEG 输出质量，范围通常为 1~100。默认值为 90。
            
    Returns:
        str:
            Base64 Data URL，可直接作为多模态模型 image_url 使用。
            JPEG 示例：data:image/jpeg;base64,/9j/4AAQSkZJRg...
            PNG 示例： data:image/png;base64,iVBORw0KGgo...

    Example:
        >>> image_url = image_to_data_url("dinner.jpg")
    """

    with Image.open(image_path) as img:
        # 修正手机照片中常见的 EXIF 旋转方向
        is_png = img.format == "PNG"
        img = ImageOps.exif_transpose(img)

        # 原始格式已在 EXIF 处理前保存。

        # --------------------------------------------------
        # 1. 调整图片尺寸
        # --------------------------------------------------
        if isinstance(max_long_edge, int) and max_long_edge >= 512:
            width, height = img.size
            long_edge = max(width, height)

            # 只缩小，不放大
            if long_edge > max_long_edge:
                scale = max_long_edge / long_edge

                new_size = (
                    max(1, round(width * scale)),
                    max(1, round(height * scale)),
                )

                img = img.resize(
                    new_size,
                    Image.Resampling.LANCZOS,
                )

        # --------------------------------------------------
        # 2. 决定输出格式
        # --------------------------------------------------

        # PNG 并且明确要求保留 PNG
        if is_png and not convert_png_to_jpeg:
            output_format = "PNG"
            mime_type = "image/png"

        else:
            # 其他情况统一转 JPEG
            output_format = "JPEG"
            mime_type = "image/jpeg"

            # JPEG 不支持透明通道。
            # 如果图片存在透明信息，先铺一层白色背景。
            if img.mode in ("RGBA", "LA") or (
                img.mode == "P" and "transparency" in img.info
            ):
                img = img.convert("RGBA")

                background = Image.new(
                    "RGBA",
                    img.size,
                    (255, 255, 255, 255),
                )

                img = Image.alpha_composite(background, img)
                img = img.convert("RGB")

            else:
                img = img.convert("RGB")

        # --------------------------------------------------
        # 3. 图片编码到内存
        # --------------------------------------------------
        buffer = BytesIO()

        if output_format == "JPEG":
            img.save(
                buffer,
                format="JPEG",
                quality=jpeg_quality,
            )
        else:
            img.save(
                buffer,
                format="PNG",
            )

        # --------------------------------------------------
        # 4. 转成 Base64 Data URL
        # --------------------------------------------------
        image_base64 = base64.b64encode(
            buffer.getvalue()
        ).decode("utf-8")

        return f"data:{mime_type};base64,{image_base64}"


def history_image_bytes(data_url: str) -> bytes:
    """将已校验的原始上传图转为存档 JPEG；独立缩放，避免重复压缩模型输入图。"""
    source = BytesIO(base64.b64decode(data_url.split(",", 1)[1]))
    converted = image_to_data_url(source, max_long_edge=1024)
    return base64.b64decode(converted.split(",", 1)[1])


def _normalize_tag(tag: str) -> str:
    """
    归一化标签名称，用于容错比较。

    例如：
    IMAGE_DESCRIPTION
    image-description
    image description
    Image_Description

    都会变成：
    imagedescription
    """
    return re.sub(r"[^a-z0-9]", "", tag.lower())


def _similarity(a: str, b: str) -> float:
    """计算两个字符串的相似度，范围 0~1。"""
    return SequenceMatcher(None, a, b).ratio()


def _is_image_description_tag(
    tag_name: str,
    threshold: float = 0.82
) -> bool:
    """
    判断标签是否可以认为是 image_description。

    支持：
    - 大小写差异
    - 下划线、横杠、空格差异
    - 少量拼写错误
    """
    target = "imagedescription"
    normalized = _normalize_tag(tag_name)

    if normalized == target:
        return True

    return _similarity(normalized, target) >= threshold


def split_image_description_with_reply(
    text: str,
    fuzzy_threshold: float = 0.82
) -> tuple[str, str]:
    """
    将 AI 回复拆分成两个字符串：

    返回：
        image_description, reply

    其中：
    - image_description：图片描述
    - reply：角色正式回复

    如果没有识别到有效图片描述：
        image_description == ""
        reply == 原始文本
    """

    if not text:
        return "", ""

    # 匹配类似：
    # <image_description>
    # </image_description>
    # <IMAGE-DESCRIPTION>
    # < image description >
    tag_pattern = re.compile(
        r"<\s*(/?)\s*([^<>]+?)\s*>",
        re.IGNORECASE
    )

    candidates = []

    for match in tag_pattern.finditer(text):
        slash = bool(match.group(1))
        raw_name = match.group(2).strip()

        # 容忍类似 <image_description/>
        raw_name = raw_name.rstrip("/").strip()

        if _is_image_description_tag(
            raw_name,
            threshold=fuzzy_threshold
        ):
            candidates.append({
                "start": match.start(),
                "end": match.end(),
                "is_closing": slash,
            })

    # 没识别到任何相关标签
    if not candidates:
        return "", text.strip()

    # 找第一个开始标签
    opening_index = None

    for i, tag in enumerate(candidates):
        if not tag["is_closing"]:
            opening_index = i
            break

    # 只有结束标签，没有开始标签
    if opening_index is None:
        return "", text.strip()

    opening = candidates[opening_index]
    remaining = candidates[opening_index + 1:]

    closing = None

    # 优先寻找标准结束标签：
    # </image_description>
    for tag in remaining:
        if tag["is_closing"]:
            closing = tag
            break

    # 容忍结束标签漏写 /
    #
    # <image_description>
    # 图片描述
    # <image_description>
    # 正式回复
    if closing is None and remaining:
        closing = remaining[0]

    # 没有结束标签，无法可靠判断图片描述结束位置
    if closing is None:
        return "", text.strip()

    image_description = text[
        opening["end"]:closing["start"]
    ].strip()

    reply = text[
        closing["end"]:
    ].strip()

    return image_description, reply


# 上传限制与前端共享；仅接受图片内容，不接受客户端指定本地路径。
MAX_CHAT_IMAGES = 3
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_CHAT_REQUEST_BYTES = 44 * 1024 * 1024  # 为三张 Base64 图片和 JSON 留出余量。
MAX_IMAGE_PIXELS = 40_000_000


def vision_unavailable_reason(config: dict) -> str | None:
    import os
    if config.get("vision", {}).get("vision") is not True:
        return "当前角色未开启图片识别。"
    if not all(os.getenv(key, "").strip() for key in (
        "LLM_VISION_API_KEY", "LLM_VISION_MODEL_ID", "LLM_VISION_BASE_URL",
    )):
        return "请先配置视觉模型的 API Key、模型名称和 API 地址。"
    return None


def prepare_chat_images(data_urls: list[str]) -> list[str]:
    """按顺序保留前三张；校验实际格式后复用现有转换函数，临时文件立即删除。"""
    import binascii
    import tempfile
    from pathlib import Path
    prepared = []
    for index, url in enumerate(data_urls[:MAX_CHAT_IMAGES], 1):
        try:
            header, encoded = url.split(",", 1)
            if header not in ("data:image/jpeg;base64", "data:image/png;base64"):
                raise ValueError("仅支持 JPEG、PNG 图片")
            if len(encoded) > 4 * ((MAX_IMAGE_BYTES + 2) // 3):
                raise ValueError("单张图片不能超过10 MiB")
            content = base64.b64decode(encoded, validate=True)
            if len(content) > MAX_IMAGE_BYTES:
                raise ValueError("单张图片不能超过10 MiB")
            with Image.open(BytesIO(content)) as img:
                if img.format not in ("JPEG", "PNG"):
                    raise ValueError("实际文件格式不是 JPEG 或 PNG")
                if img.width * img.height > MAX_IMAGE_PIXELS:
                    raise ValueError("图片像素过多，请先缩小图片")
                img.verify()
            with tempfile.TemporaryDirectory(prefix="aipartner-image-") as tmp:
                path = Path(tmp) / "upload"
                path.write_bytes(content)
                prepared.append(image_to_data_url(str(path)))
        except (ValueError, OSError, binascii.Error, Image.DecompressionBombError) as error:
            raise ValueError(f"图片{index}无法处理：{error}") from error
    return prepared


class ChatUploadLimit:
    """在 JSON 解析前限制聊天请求体，包含没有 Content-Length 的上传。"""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (scope["type"] != "http" or scope.get("method") != "POST"
                or not scope.get("path", "").endswith("/chat")):
            return await self.app(scope, receive, send)
        chunks, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > MAX_CHAT_REQUEST_BYTES:
                body = '{"detail":"图片请求过大，请减少图片数量或大小。"}'.encode("utf-8")
                await send({"type": "http.response.start", "status": 413,
                            "headers": [(b"content-type", b"application/json; charset=utf-8")]})
                await send({"type": "http.response.body", "body": body})
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        body = b"".join(chunks)
        chunks.clear()
        delivered = False
        async def replay():
            nonlocal delivered, body
            if delivered:
                return await receive()
            delivered = True
            result = {"type": "http.request", "body": body, "more_body": False}
            body = b""
            return result
        await self.app(scope, replay, send)
