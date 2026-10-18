# spikes/check_anthropic.py
from dotenv import load_dotenv
import anthropic
load_dotenv()
client = anthropic.Anthropic()
msg = client.messages.create(
    model="claude-haiku-5-5",
    # Room for thinking, which Haiku 5.5 does by default and which counts
    # against this cap; low effort keeps it short.
    max_tokens=1024,
    output_config={"effort": "low"},
    messages=[{"role": "user", "content": "Reply with exactly: Norm is ready."}],
)
# By type, not position: a thinking block can come first.
print(next(block.text for block in msg.content if block.type == "text"))