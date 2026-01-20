import json
from openai import OpenAI
from config import FORM_COLUMNS, latest_structured_data
from backend.nutils.file_utils import encode_image_to_base64, get_image_mime_type
import os

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def process_image_with_openai_vision(file_path):
    """
    Process image using OpenAI Vision API to extract and structure form data
    """
    try:
        print(f"Processing image: {file_path}")
        
        base64_image = encode_image_to_base64(file_path)
        mime_type = get_image_mime_type(file_path)
        
        column_list = ", ".join(FORM_COLUMNS)
        
        prompt = f"""
        You are analyzing a BEDROOM CHECKLIST form image. Extract all visible information and organize it into a JSON format using ONLY these exact field names.

        CRITICAL INSTRUCTIONS FOR CHECKBOXES - READ CAREFULLY:
        
        1. ONLY mark a checkbox field as "✓" if you can see CLEAR EVIDENCE of a checkmark, tick mark, X mark, or any marking inside that specific checkbox
        2. If a checkbox appears empty, blank, or unmarked, set it to null (not "✗", not false, not "")
        3. DO NOT assume checkboxes are marked based on context or other information
        4. DO NOT mark all checkboxes in a section just because one is marked
        5. BE EXTREMELY CONSERVATIVE - when in doubt, use null
        6. For text fields, extract the exact text written (including handwritten text)
        7. Look carefully at dates, names, addresses, and other handwritten information
        8. Return valid JSON only

        FIELD NAMES TO USE:
        {column_list}

        Return only the JSON object with the extracted data. Do not include any explanatory text.
        """

        print("Sending request to OpenAI Vision API...")
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": "You are a precise data extraction expert specializing in form analysis. For checkboxes, be extremely conservative - only mark as checked (✓) if you clearly see a checkmark, tick, X, or other mark inside the checkbox. All empty/unmarked checkboxes should be null. Return only valid JSON with no additional text."
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_image}", "detail": "high"}}
                    ]
                }
            ],
            temperature=0,
            max_tokens=2000
        )

        reply = response.choices[0].message.content.strip()
        print(f"OpenAI Vision response length: {len(reply)}")
        
        if reply.startswith('```json'):
            reply = reply[7:]
        if reply.endswith('```'):
            reply = reply[:-3]
        reply = reply.strip()

        try:
            structured_data = json.loads(reply)
            final_data = {}
            checkbox_fields = [
                'bedside_cabinets_floating', 'bedside_cabinets_fitted', 'bedside_cabinets_freestand',
                'dresser_desk_yes', 'dresser_desk_no', 'internal_mirror_yes', 'internal_mirror_no',
                'mirror_silver', 'mirror_bronze', 'mirror_grey', 'soffit_lights_spot', 'soffit_lights_strip',
                'soffit_lights_cool_white', 'soffit_lights_warm_white', 'gable_lights_black', 'gable_lights_white',
                'carpet_protection', 'floor_tile_protection', 'no_floor'
            ]
            
            for column in FORM_COLUMNS:
                value = structured_data.get(column, None)
                if column in checkbox_fields:
                    final_data[column] = "✓" if value in ["✓", "checked", True, "true"] else None
                else:
                    final_data[column] = None if value in ["", "null", "None"] else value
            
            global latest_structured_data
            latest_structured_data.update(final_data)
            return final_data
            
        except json.JSONDecodeError as e:
            print(f"JSON parsing error: {e}")
            print(f"Raw response: {reply}")
            return {"error": "Failed to parse JSON response from OpenAI Vision", "raw_response": reply, "json_error": str(e)}
            
    except Exception as e:
        print(f"OpenAI Vision API error: {str(e)}")
        return {"error": f"OpenAI Vision API error: {str(e)}"}