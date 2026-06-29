from decouple import config
from openai import OpenAI



client = OpenAI(
    api_key= config("OPENROUTER_API_KEY"),
    base_url= config("BASE_URL")
)

response = client.chat.completions.create(
    model="openai/gpt-4o-mini",
    messages=[
        {"role": "user", 
         "content": "Write a Python hello world program"}
    ]
)

print(response.choices[0].message.content)