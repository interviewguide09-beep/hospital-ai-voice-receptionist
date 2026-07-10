import json
from typing import Any, Dict, List, Optional, Type
import google.generativeai as genai
from google.generativeai.types import GenerateContentResponse
from pydantic import BaseModel
from app.core.config import settings
from app.core.logging import gemini_logger
from app.core.exceptions import ThirdPartyException

class GeminiService:
    def __init__(self):
        # Configure Gemini SDK
        if not settings.GEMINI_API_KEY:
            gemini_logger.critical("GEMINI_API_KEY is not set in environment settings.")
            raise ValueError("GEMINI_API_KEY is required.")
        genai.configure(api_key=settings.GEMINI_API_KEY)
        self.model_name = settings.GEMINI_MODEL

    async def generate_structured_output_async(
        self,
        prompt: str,
        response_schema: Type[BaseModel],
        system_instruction: Optional[str] = None
    ) -> BaseModel:
        """Generates structured content conforming to a specific Pydantic schema using Gemini structured JSON response features."""
        gemini_logger.debug(f"Requesting structured output for model: {self.model_name}")
        try:
            model = genai.GenerativeModel(
                model_name=self.model_name,
                system_instruction=system_instruction
            )
            
            # Configure generation configuration to force JSON schema output
            generation_config = {
                "response_mime_type": "application/json",
                "response_schema": response_schema,
                "temperature": 0.1,  # Low temperature for highly precise output
            }
            
            # Run the generation natively async
            response = await model.generate_content_async(
                contents=prompt,
                generation_config=generation_config
            )
            
            # Parse the text response back into the Pydantic schema
            parsed_data = response_schema.model_validate_json(response.text)
            return parsed_data
        except Exception as e:
            gemini_logger.error(f"Gemini structured output generation failed: {str(e)}")
            raise ThirdPartyException(f"Gemini service failed: {str(e)}")

    async def generate_chat_turn_async(
        self,
        history: List[Dict[str, str]],
        system_instruction: str,
        tools: Optional[List[Any]] = None
    ) -> Dict[str, Any]:
        """Generates a standard conversation chat turn, supporting optional function calling tools."""
        gemini_logger.debug(f"Executing chat turn with system instruction length: {len(system_instruction)}")
        try:
            model = genai.GenerativeModel(
                model_name=self.model_name,
                system_instruction=system_instruction,
                tools=tools
            )

            # Map the standard role transcript format to Gemini Content types
            # role must be "user" or "model"
            gemini_contents = []
            for turn in history:
                role = "user" if turn["role"] == "user" else "model"
                gemini_contents.append({
                    "role": role,
                    "parts": [{"text": turn["content"]}]
                })

            generation_config = {
                "temperature": 0.2
            }

            response = await model.generate_content_async(
                contents=gemini_contents,
                generation_config=generation_config
            )

            # Check if there are function calls returned
            function_calls = []
            if response.candidates and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    if hasattr(part, "function_call") and part.function_call:
                        fc = part.function_call
                        function_calls.append({
                            "name": fc.name,
                            "args": dict(fc.args)
                        })

            return {
                "text": response.text if response.text else "",
                "function_calls": function_calls
            }
        except Exception as e:
            gemini_logger.error(f"Gemini chat turn generation failed: {str(e)}")
            raise ThirdPartyException(f"Gemini chat service failed: {str(e)}")
