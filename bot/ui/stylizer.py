"""Convert only bold-heading contents to Unicode mathematical alphabets."""
from __future__ import annotations

import re


def _make_map(upper: str, lower: str, digits: str = "") -> dict[str, str]:
    source = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    target = upper + lower + digits
    return {a: b for a, b in zip(source, target) if b != " "}

MAPS: dict[str, dict[str, str]] = {
    "bold": _make_map("𝐀𝐁𝐂𝐃𝐄𝐅𝐆𝐇𝐈𝐉𝐊𝐋𝐌𝐍𝐎𝐏𝐐𝐑𝐒𝐓𝐔𝐕𝐖𝐗𝐘𝐙", "𝐚𝐛𝐜𝐝𝐞𝐟𝐠𝐡𝐢𝐣𝐤𝐥𝐦𝐧𝐨𝐩𝐪𝐫𝐬𝐭𝐮𝐯𝐰𝐱𝐲𝐳", "𝟎𝟏𝟐𝟑𝟒𝟓𝟔𝟕𝟖𝟗"),
    "sans": _make_map("𝗔𝗕𝗖𝗗𝗘𝗙𝗚𝗛𝗜𝗝𝗞𝗟𝗠𝗡𝗢𝗣𝗤𝗥𝗦𝗧𝗨𝗩𝗪𝗫𝗬𝗭", "𝗮𝗯𝗰𝗱𝗲𝗳𝗴𝗵𝗶𝗷𝗸𝗹𝗺𝗻𝗼𝗽𝗾𝗿𝘀𝘁𝘂𝘃𝘄𝘅𝘆𝘇", "𝟬𝟭𝟮𝟯𝟰𝟱𝟲𝟳𝟴𝟵"),
    "bolditalic": _make_map("𝑨𝑩𝑪𝑫𝑬𝑭𝑮𝑯𝑰𝑱𝑲𝑳𝑴𝑵𝑶𝑷𝑸𝑹𝑺𝑻𝑼𝑽𝑾𝑿𝒀𝒁", "𝒂𝒃𝒄𝒅𝒆𝒇𝒈𝒉𝒊𝒋𝒌𝒍𝒎𝒏𝒐𝒑𝒒𝒓𝒔𝒕𝒖𝒗𝒘𝒙𝒚𝒛"),
    "script": _make_map("𝓐𝓑𝓒𝓓𝓔𝓕𝓖𝓗𝓘𝓙𝓚𝓛𝓜𝓝𝓞𝓟𝓠𝓡𝓢𝓣𝓤𝓥𝓦𝓧𝓨𝓩", "𝓪𝓫𝓬𝓭𝓮𝓯𝓰𝓱𝓲𝓳𝓴𝓵𝓶𝓷𝓸𝓹𝓺𝓻𝓼𝓽𝓾𝓿𝔀𝔁𝔂𝔃"),
    "mono": _make_map("𝙰𝙱𝙲𝙳𝙴𝙵𝙶𝙷𝙸𝙹𝙺𝙻𝙼𝙽𝙾𝙿𝚀𝚁𝚂𝚃𝚄𝚅𝚆𝚇𝚈𝚉", "𝚊𝚋𝚌𝚍𝚎𝚏𝚐𝚑𝚒𝚓𝚔𝚕𝚖𝚗𝚘𝚙𝚚𝚛𝚜𝚝𝚞𝚟𝚠𝚡𝚢𝚣", "𝟶𝟷𝟸𝟹𝟺𝟻𝟼𝟽𝟾𝟿"),
    "smallcaps": {**dict(zip("abcdefghijklmnopqrstuvwxyz", "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀꜱᴛᴜᴠᴡxʏᴢ")), **dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "ABCDEFGHIJKLMNOPQRSTUVWXYZ"))},
}

_ENTITY_RE = re.compile(r"(&#\d+;|&#x[0-9a-fA-F]+;|&[a-zA-Z][a-zA-Z0-9]+;)")
_BOLD_RE = re.compile(r"<b>(.*?)</b>", flags=re.DOTALL | re.IGNORECASE)


def _convert_text(text: str, mapping: dict[str, str]) -> str:
    # Entities and inline code/pre tags are protected from Unicode conversion.
    protected_re = re.compile(r"(&#\d+;|&#x[0-9a-fA-F]+;|&[a-zA-Z][a-zA-Z0-9]+;|<code\b[^>]*>.*?</code>|<pre\b[^>]*>.*?</pre>)", re.IGNORECASE | re.DOTALL)
    parts = protected_re.split(text)
    for index in range(0, len(parts), 2):
        parts[index] = "".join(mapping.get(char, char) for char in parts[index])
    return "".join(parts)


def stylize(html: str, style: str = "bold") -> str:
    """Stylize only text enclosed in b-tags; entities and code/pre blocks remain intact."""
    mapping = MAPS.get(style, MAPS["bold"])
    return _BOLD_RE.sub(lambda match: "<b>" + _convert_text(match.group(1), mapping) + "</b>", html)


if __name__ == "__main__":
    sample = "<b>Hello &amp; World</b> normal body <code>print('ok')</code>"
    result = stylize(sample, "bold")
    assert result.startswith("<b>𝐇𝐞𝐥𝐥𝐨 &amp; 𝐖𝐨𝐫𝐥𝐝</b>")
    assert " normal body " in result
    assert "<code>print('ok')</code>" in result
    assert stylize("<b>g'o</b>", "bold") == "<b>𝐠'𝐨</b>"
    assert stylize("<b>Run <code>print()</code></b>", "bold") == "<b>𝐑𝐮𝐧 <code>print()</code></b>"
