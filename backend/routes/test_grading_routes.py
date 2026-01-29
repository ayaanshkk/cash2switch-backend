from flask import Blueprint, request, jsonify, g
from werkzeug.utils import secure_filename
from functools import wraps
import os
import json
import base64
import logging
from datetime import datetime
from typing import Dict, List, Optional
from openai import OpenAI
import fitz  # PyMuPDF
from PIL import Image
import io
import jwt

from backend.db import SessionLocal
from backend.models import User, TestResult

test_grading_bp = Blueprint("test_grading", __name__, url_prefix="/api/test-grading")

# Initialize OpenAI client
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ==================== AUTH DECORATOR ====================
def token_required(f):
    """Decorator to require JWT authentication"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        
        # Get token from header
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            try:
                token = auth_header.split(" ")[1]  # Bearer <token>
            except IndexError:
                return jsonify({"error": "Invalid token format"}), 401
        
        if not token:
            return jsonify({"error": "Authentication token is missing"}), 401
        
        try:
            # Decode token
            secret_key = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
            payload = jwt.decode(token, secret_key, algorithms=['HS256'])
            
            # Get user from database
            db = SessionLocal()
            user = db.query(User).filter(User.id == payload['user_id']).first()
            db.close()
            
            if not user or not user.is_active:
                return jsonify({"error": "Invalid or inactive user"}), 401
            
            # Store user info in g for use in route
            g.user_id = user.id
            g.user = user
            
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token has expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Invalid token"}), 401
        except Exception as e:
            return jsonify({"error": f"Authentication error: {str(e)}"}), 401
        
        return f(*args, **kwargs)
    
    return decorated

# Answer keys - CORRECTED
ANSWER_KEYS = {
    "BOPT": {
        "total_questions": 20,
        "format": "standard",
        "answers": {
            "1": "FALSE", "2": "FALSE", "3": "FALSE", "4": "FALSE", "5": "FALSE",
            "6": "TRUE", "7": "TRUE", "8": "FALSE", "9": "TRUE", "10": "TRUE",
            "11": "TRUE", "12": "TRUE", "13": "FALSE", "14": "TRUE", "15": "TRUE",
            "16": "FALSE", "17": "TRUE", "18": "TRUE", "19": "FALSE", "20": "FALSE"
        }
    },
    "REACH_TRUCK": {
        "total_questions": 24,
        "format": "standard",
        "answers": {
            "1": "FALSE", "2": "FALSE", "3": "FALSE", "4": "FALSE", "5": "FALSE",
            "6": "TRUE", "7": "TRUE", "8": "TRUE", "9": "TRUE", "10": "FALSE",
            "11": "TRUE", "12": "TRUE", "13": "FALSE", "14": "FALSE", "15": "FALSE",
            "16": "TRUE", "17": "TRUE", "18": "FALSE", "19": "TRUE", "20": "TRUE",
            "21": "TRUE", "22": "FALSE", "23": "TRUE", "24": "TRUE"
        }
    },
    "FORKLIFT": {
        "total_questions": 24,
        "format": "special",
        "answers": {
            "1a": "FALSE", "1b": "FALSE", "1c": "FALSE", "1d": "FALSE", "1e": "FALSE",
            "2": "TRUE", "3": "TRUE", "4": "TRUE", "5": "TRUE", "6": "TRUE",
            "7": "TRUE", "8": "FALSE", "9": "TRUE", "10": "FALSE", "11": "FALSE",
            "12": "FALSE", "13": "TRUE", "14": "FALSE", "15": "TRUE", "16": "FALSE",
            "17": "FALSE", "18": "TRUE", "19": "TRUE", "20": "BALANCE"
        }
    },
    "STACKER": {
        "total_questions": 24,
        "format": "standard",
        "answers": {
            "1": "FALSE", "2": "FALSE", "3": "FALSE", "4": "FALSE", "5": "FALSE",
            "6": "TRUE", "7": "TRUE", "8": "TRUE", "9": "TRUE", "10": "TRUE",
            "11": "FALSE", "12": "FALSE", "13": "FALSE", "14": "FALSE", "15": "FALSE",
            "16": "FALSE", "17": "TRUE", "18": "TRUE", "19": "FALSE", "20": "FALSE",
            "21": "TRUE", "22": "TRUE", "23": "FALSE", "24": "TRUE"
        }
    }
}

# ==================== HELPER FUNCTIONS ====================

def convert_pdf_to_image(pdf_bytes: bytes) -> bytes:
    """Convert PDF to high-quality image"""
    try:
        pdf_document = fitz.open(stream=pdf_bytes, filetype="pdf")
        page = pdf_document[0]
        mat = fitz.Matrix(600/72, 600/72)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img_bytes = pix.tobytes("png")
        img = Image.open(io.BytesIO(img_bytes))
        img_byte_arr = io.BytesIO()
        img.convert('RGB').save(img_byte_arr, format='JPEG', quality=95, subsampling=0)
        img_byte_arr.seek(0)
        pdf_document.close()
        return img_byte_arr.read()
    except Exception as e:
        raise Exception(f"PDF conversion error: {str(e)}")


def enhance_image_quality(image_bytes: bytes) -> bytes:
    """Enhance image quality for better OCR"""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode != 'RGB':
            img = img.convert('RGB')
        width, height = img.size
        if width < 2400:
            scale = 2400 / width
            new_width = int(width * scale)
            new_height = int(height * scale)
            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='JPEG', quality=95, subsampling=0)
        img_byte_arr.seek(0)
        return img_byte_arr.read()
    except Exception as e:
        return image_bytes


def process_uploaded_file(file_bytes: bytes, content_type: str) -> bytes:
    """Process uploaded file (PDF or image)"""
    if content_type == 'application/pdf':
        return convert_pdf_to_image(file_bytes)
    elif content_type.startswith('image/'):
        return enhance_image_quality(file_bytes)
    else:
        raise Exception("Unsupported file type. Only PDF and images are supported.")


def extract_answers_with_gpt4_vision(image_bytes: bytes) -> Dict:
    """Extract answers from test paper using GPT-4 Vision"""
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    
    prompt = """Analyze this MHE test paper image with EXTREME PRECISION.

TASK: Extract student answers by detecting checkmark positions.

MHE TYPE DETECTION:
- "BOPT" in header → BOPT (20 questions)
- "Reach Truck" → REACH_TRUCK (24 questions)
- "Forklift" → FORKLIFT (24 questions, special format)
- "Stacker" → STACKER (20 questions)

TABLE STRUCTURE:
After each question, there are 3 answer columns:
Column 1 (LEFTMOST): TRUE
Column 2 (MIDDLE): FALSE
Column 3 (RIGHTMOST): Don't Know

CHECKMARK DETECTION RULES:
1. Look at EACH row individually
2. Identify ANY mark (✓, ✔, √, V, tick) in the answer columns
3. Determine the HORIZONTAL POSITION of the mark
4. LEFT position → "TRUE"
5. MIDDLE position → "FALSE"
6. RIGHT position → "Don't Know"
7. No mark → "BLANK"

SPECIAL: FORKLIFT FORMAT
- Question 1 has 5 sub-parts without numbers:
  1a: "For Outdoor applications"
  1b: "As a tow-truck for trailers"
  1c: "To tow other trucks"
  1d: "To transport / lift passengers"
  1e: "For Driving on gravel or grass"
- Then questions 2-20
- Question 20: Fill-in-blank (extract written word)

Return JSON:
{
    "mhe_type": "FORKLIFT",
    "participant_name": "",
    "company": "",
    "date": "",
    "place": "",
    "test_type": "Post test",
    "total_questions": 24,
    "answers": {
        "1a": "FALSE",
        "1b": "FALSE",
        ...
        "20": "BALANCE"
    }
}"""
    
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/jpeg;base64,{base64_image}",
                        "detail": "high"
                    }}
                ]
            }],
            max_tokens=4000,
            temperature=0
        )
        
        result_text = response.choices[0].message.content.strip()
        result_text = result_text.replace("```json", "").replace("```", "").strip()
        return json.loads(result_text)
        
    except Exception as e:
        raise Exception(f"GPT-4 Vision error: {str(e)}")


def grade_test_internal(extracted_data: Dict) -> Dict:
    """Grade the test based on extracted answers"""
    mhe_type = extracted_data.get("mhe_type", "BOPT").upper().strip()
    
    # Normalize MHE type
    if "REACH" in mhe_type:
        mhe_type = "REACH_TRUCK"
    elif "FORKLIFT" in mhe_type or "FORK" in mhe_type:
        mhe_type = "FORKLIFT"
    elif "STACKER" in mhe_type:
        mhe_type = "STACKER"
    else:
        mhe_type = "BOPT"
    
    if mhe_type not in ANSWER_KEYS:
        raise Exception(f"Unknown MHE type: {mhe_type}")
    
    answer_key_data = ANSWER_KEYS[mhe_type]
    answer_key = answer_key_data["answers"]
    total_questions = answer_key_data["total_questions"]
    
    answers = extracted_data.get("answers", {})
    details = []
    total_marks_obtained = 0
    
    for question_key in answer_key.keys():
        correct_answer = answer_key[question_key]
        student_answer = answers.get(question_key, "BLANK")
        
        # Handle fill-in-the-blank questions (like BALANCE)
        if correct_answer.isalpha() and len(correct_answer) > 4:
            is_correct = student_answer.upper().strip() == correct_answer.upper().strip()
        else:
            is_correct = student_answer == correct_answer
        
        marks_obtained = 1 if is_correct else 0
        remark = "Correct" if is_correct else "Wrong"
        
        if is_correct:
            total_marks_obtained += 1
        
        details.append({
            "question_number": question_key,
            "student_answer": student_answer,
            "correct_answer": correct_answer,
            "is_correct": is_correct,
            "remark": remark,
            "marks_obtained": marks_obtained
        })
    
    percentage = (total_marks_obtained / total_questions) * 100
    grade = "Pass" if percentage >= 70 else "Fail"
    
    return {
        "participant_name": extracted_data.get("participant_name", "Unknown"),
        "company": extracted_data.get("company", "Unknown"),
        "date": extracted_data.get("date", "Unknown"),
        "place": extracted_data.get("place", "Unknown"),
        "test_type": extracted_data.get("test_type", "Unknown"),
        "mhe_type": mhe_type,
        "answers": answers,
        "total_marks_obtained": total_marks_obtained,
        "total_marks": total_questions,
        "percentage": round(percentage, 2),
        "grade": grade,
        "details": details
    }


# ==================== ROUTES ====================

@test_grading_bp.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "message": "Test grading system is running",
        "supported_mhe": list(ANSWER_KEYS.keys()),
        "ai_model": "GPT-4o"
    }), 200


@test_grading_bp.route("/answer-keys", methods=["GET"])
@token_required
def get_answer_keys():
    """Get all answer keys"""
    return jsonify({"answer_keys": ANSWER_KEYS}), 200


@test_grading_bp.route("/extract-answers", methods=["POST"])
@token_required
def extract_answers():
    """Step 1: Extract answers using AI - returns data for manual review"""
    try:
        # Check if file is present
        if 'file' not in request.files:
            return jsonify({"error": "No file provided"}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({"error": "No file selected"}), 400
        
        # Validate file type
        if not (file.content_type.startswith('image/') or file.content_type == 'application/pdf'):
            return jsonify({"error": "File must be an image or PDF"}), 400
        
        # Read and process file
        file_bytes = file.read()
        image_bytes = process_uploaded_file(file_bytes, file.content_type)
        
        # Extract with AI
        extracted_data = extract_answers_with_gpt4_vision(image_bytes)
        
        # Convert image to base64 for frontend display
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')
        
        return jsonify({
            "mhe_type": extracted_data.get("mhe_type", "BOPT"),
            "participant_name": extracted_data.get("participant_name", ""),
            "company": extracted_data.get("company", ""),
            "date": extracted_data.get("date", ""),
            "place": extracted_data.get("place", ""),
            "test_type": extracted_data.get("test_type", ""),
            "total_questions": extracted_data.get("total_questions", 20),
            "answers": extracted_data.get("answers", {}),
            "image_base64": image_base64
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@test_grading_bp.route("/grade-with-corrections", methods=["POST"])
@token_required
def grade_with_corrections():
    """Step 2: Grade test with manually corrected answers and save to database"""
    db = SessionLocal()
    try:
        logging.info("Received request to /grade-with-corrections")
        data = request.get_json()
        
        if not data:
            logging.error("No data provided to grade-with-corrections")
            return jsonify({"error": "No data provided"}), 400
        
        logging.info("Data received: %s", list(data.keys()))
        extracted_data = data.get("extracted_data", {})
        corrected_answers = data.get("corrected_answers", {})
        logging.info("Extracted data keys: %s, corrected answers count: %s", list(extracted_data.keys()), len(corrected_answers))
        if 'image_base64' in extracted_data:
            logging.info("Image base64 length: %s characters", len(extracted_data['image_base64']))
        
        # Save image before modifying extracted_data
        image_base64 = extracted_data.get("image_base64", "")
        # Use corrected answers
        extracted_data["answers"] = corrected_answers
        logging.info("Starting grading process")
        result = grade_test_internal(extracted_data)
        logging.info("Grading complete: %s (%s%%)", result['grade'], result['percentage'])
        
        # Save to database
        test_result = TestResult(
            user_id=g.user_id,
            participant_name=result["participant_name"],
            company=result["company"],
            date=result["date"],
            place=result["place"],
            test_type=result["test_type"],
            mhe_type=result["mhe_type"],
            total_marks_obtained=result["total_marks_obtained"],
            total_marks=result["total_marks"],
            percentage=result["percentage"],
            grade=result["grade"],
            answers_json=json.dumps(result["answers"]),
            details_json=json.dumps(result["details"]),
            image_base64=image_base64
        )
        
        db.add(test_result)
        db.commit()
        db.refresh(test_result)
        logging.info("Successfully saved test result with ID: %s", test_result.id)
        result["id"] = test_result.id
        result["created_at"] = test_result.created_at.isoformat() if test_result.created_at else None
        return jsonify(result), 200
        
    except Exception as e:
        db.rollback()
        logging.exception("Error in grade_with_corrections: %s", e)
        
        return jsonify({
            "error": str(e),
            "error_type": type(e).__name__
        }), 500
    finally:
        db.close()


@test_grading_bp.route("/results", methods=["GET"])
@token_required
def get_test_results():
    """Get all test results for current user"""
    db = SessionLocal()
    try:
        skip = request.args.get('skip', 0, type=int)
        limit = request.args.get('limit', 50, type=int)
        
        results = db.query(TestResult)\
            .filter(TestResult.user_id == g.user_id)\
            .order_by(TestResult.created_at.desc())\
            .offset(skip)\
            .limit(limit)\
            .all()
        
        response = []
        for result in results:
            response.append({
                "id": result.id,
                "participant_name": result.participant_name,
                "company": result.company,
                "date": result.date,
                "place": result.place,
                "test_type": result.test_type,
                "mhe_type": result.mhe_type,
                "answers": json.loads(result.answers_json) if result.answers_json else {},
                "total_marks_obtained": result.total_marks_obtained,
                "total_marks": result.total_marks,
                "percentage": result.percentage,
                "grade": result.grade,
                "details": json.loads(result.details_json) if result.details_json else [],
                "created_at": result.created_at.isoformat() if result.created_at else None
            })
        
        return jsonify(response), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@test_grading_bp.route("/results/<int:result_id>", methods=["GET"])
@token_required
def get_test_result(result_id):
    """Get a specific test result"""
    db = SessionLocal()
    try:
        result = db.query(TestResult)\
            .filter(TestResult.id == result_id, TestResult.user_id == g.user_id)\
            .first()
        
        if not result:
            return jsonify({"error": "Test result not found"}), 404
        
        return jsonify({
            "id": result.id,
            "participant_name": result.participant_name,
            "company": result.company,
            "date": result.date,
            "place": result.place,
            "test_type": result.test_type,
            "mhe_type": result.mhe_type,
            "answers": json.loads(result.answers_json) if result.answers_json else {},
            "total_marks_obtained": result.total_marks_obtained,
            "total_marks": result.total_marks,
            "percentage": result.percentage,
            "grade": result.grade,
            "details": json.loads(result.details_json) if result.details_json else [],
            "created_at": result.created_at.isoformat() if result.created_at else None
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@test_grading_bp.route("/results/<int:result_id>", methods=["DELETE"])
@token_required
def delete_test_result(result_id):
    """Delete a specific test result"""
    db = SessionLocal()
    try:
        result = db.query(TestResult)\
            .filter(TestResult.id == result_id, TestResult.user_id == g.user_id)\
            .first()
        
        if not result:
            return jsonify({"error": "Test result not found"}), 404
        
        db.delete(result)
        db.commit()
        
        return jsonify({"message": "Test result deleted successfully"}), 200
        
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()