with open("templates/qa/_floating_widget.html", "r") as f:
    content = f.read()

import re
match = re.search(r"const endpoint = isVideo.+?;", content)
print(match.group(0) if match else "Not found")
