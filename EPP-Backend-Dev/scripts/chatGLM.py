import openai
from django.conf import settings

server_url = settings.REMOTE_CHAT_CHAT_GLM_PATH

if __name__ == "__main__":
    openai.api_base = f"{server_url}/v1"
    openai.api_key = "none"
    history = []
    while True:
        user_input = input("用户：")
        history.append({"role": "user", "content": user_input})
        if user_input.lower() == "exit":
            break
        response = openai.ChatCompletion.create(
            model="chatglm2-6b", messages=history, stream=False
        )
        if response.choices[0].message.role == "assistant":
            print("ChatGLM2-6B：", response.choices[0].message.content)
            history.append(
                {"role": "assistant", "content": response.choices[0].message.content}
            )
