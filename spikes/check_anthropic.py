# spikes/check_anthropic.py
from dotenv import load_dotenv
import anthropic
load_dotenv()
client = anthropic.Anthropic()
msg = client.messages.create(
    model="claude-haiku-4-5",
    max_tokens=50,
    messages=[{"role": "user", "content": "Reply with exactly: Norm is ready."}],
)
print(msg.content[0].text)