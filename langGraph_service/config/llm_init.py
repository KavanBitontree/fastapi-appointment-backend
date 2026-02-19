# """
# LLM Initialization for LangGraph
# Uses Groq for fast inference with llama-3.3-70b-versatile
# """

# from langchain_groq import ChatGroq
# from os import getenv
# from dotenv import load_dotenv

# load_dotenv()

# llm = ChatGroq(
#     model="llama-3.3-70b-versatile",
#     api_key=getenv("GROQ_API_KEY"),
#     temperature=0.3,
# )

from langchain_openai import ChatOpenAI
from os import getenv
from dotenv import load_dotenv

load_dotenv()


llm = ChatOpenAI(
    model="openai/gpt-oss-120b",
    openai_api_key=getenv("OPENROUTER_API_KEY"),
    openai_api_base="https://openrouter.ai/api/v1",
    temperature=0.3,
)

if __name__ == "__main__":
    response = llm.invoke("Who won the latest cricket world cup?")
    print(response.content)
