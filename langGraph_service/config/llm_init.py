"""
LLM Initialization for LangGraph
Uses Groq for fast inference with llama-3.3-70b-versatile
"""

from langchain_groq import ChatGroq
from os import getenv
from dotenv import load_dotenv

load_dotenv()

llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    api_key=getenv("GROQ_API_KEY"),
    temperature=0.3,
)