import os
import json
import re
from collections import Counter
import google.generativeai as genai
from flask import Flask, request, render_template, jsonify
from dotenv import load_dotenv
import docx
import fitz
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
load_dotenv()

api_key = os.getenv("API_KEY")
if not api_key:
    logging.critical("API_KEY not found in .env file")
else:
    logging.info(f"API Key loaded: {api_key[:4]}...")

app = Flask(__name__)
model = None

try:
    if api_key:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.0-flash')
        logging.info("Gemini model initialized")
except Exception as e:
    logging.critical(f"Error initializing Gemini: {e}")

def extract_text(file_stream, filename):
    """Extract text from PDF or DOCX files"""
    try:
        file_stream.seek(0)
        if filename.endswith(".pdf"):
            doc = fitz.open(stream=file_stream.read(), filetype="pdf")
            text = "".join(page.get_text() for page in doc)
            return text
        elif filename.endswith(".docx"):
            doc = docx.Document(file_stream)
            text = "\n".join(para.text for para in doc.paragraphs)
            return text
        elif filename.endswith(".txt"):
            return file_stream.read().decode("utf-8")
        else:
            return ""
    except Exception as e:
        logging.error(f"Error extracting text from {filename}: {e}")
        return ""

def extract_keywords(text):
    """Extract meaningful keywords from text"""
    text = text.lower()
    # Remove common words
    stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 
                  'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'been', 'be',
                  'have', 'has', 'do', 'does', 'did', 'will', 'would', 'could', 'should',
                  'may', 'might', 'must', 'can', 'this', 'that', 'these', 'those', 'i',
                  'you', 'he', 'she', 'it', 'we', 'they', 'what', 'which', 'who', 'when',
                  'where', 'why', 'how', 'all', 'each', 'every', 'both', 'few', 'more',
                  'most', 'other', 'some', 'such', 'no', 'nor', 'not', 'only', 'own',
                  'same', 'so', 'than', 'too', 'very'}
    
    # Extract words (3+ characters)
    words = re.findall(r'\b[a-z]+\b', text)
    keywords = [w for w in words if len(w) >= 3 and w not in stop_words]
    return keywords

def calculate_match_score(resume_text, jd_text):
    """Calculate matching score based on keyword overlap"""
    resume_keywords = extract_keywords(resume_text)
    jd_keywords = extract_keywords(jd_text)
    
    # Get unique keywords from JD
    jd_unique = set(jd_keywords)
    resume_set = set(resume_keywords)
    
    if not jd_unique:
        return 0, 0, 0, 0, "Unable to analyze"
    
    # Calculate keyword match percentage
    matched_keywords = jd_unique & resume_set
    keywords_match = int((len(matched_keywords) / len(jd_unique)) * 100)
    
    # Extract skills (common technical keywords)
    tech_skills = {'python', 'java', 'javascript', 'sql', 'aws', 'azure', 'gcp',
                   'react', 'django', 'flask', 'node', 'docker', 'kubernetes',
                   'machine', 'learning', 'data', 'analysis', 'analytics', 'api',
                   'rest', 'graphql', 'devops', 'ci', 'cd', 'git', 'linux', 'windows',
                   'agile', 'scrum', 'jira', 'mongodb', 'postgresql', 'redis'}
    
    jd_skills = jd_unique & tech_skills
    resume_skills = resume_set & tech_skills
    matched_skills = jd_skills & resume_skills
    
    skills_match = int((len(matched_skills) / len(jd_skills)) * 100) if jd_skills else 0
    
    # Experience match based on years
    experience_match = 0
    years_match = re.findall(r'(\d+)\s*(?:years?|yrs)', resume_text, re.IGNORECASE)
    if years_match:
        years = int(years_match[0])
        # If they have relevant experience, increase score
        if years > 0:
            experience_match = min(int((years / 10) * 100), 100)
    
    # Tone match - check for professional language
    professional_terms = {'achieved', 'improved', 'led', 'managed', 'developed', 
                         'implemented', 'designed', 'created', 'optimized', 'increased',
                         'delivered', 'contributed', 'collaborated', 'proven'}
    prof_in_resume = resume_set & professional_terms
    tone_match = int((len(prof_in_resume) / max(1, len(professional_terms))) * 100)
    
    # Overall score
    overall_score = int((skills_match * 0.4) + (experience_match * 0.3) + 
                        (keywords_match * 0.2) + (tone_match * 0.1))
    
    summary = f"Your resume matches {keywords_match}% of job keywords with {skills_match}% skill alignment."
    
    return overall_score, skills_match, experience_match, keywords_match, summary

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/customize', methods=['POST'])
def customize_resume():
    """Tailor resume to job description"""
    if not model:
        return jsonify({"error": "Model not available"}), 500
    
    if 'resume' not in request.files or 'job_description' not in request.files:
        return jsonify({"error": "Missing files"}), 400
    
    resume_file = request.files['resume']
    jd_file = request.files['job_description']
    
    try:
        resume_text = extract_text(resume_file.stream, resume_file.filename)
        jd_text = extract_text(jd_file.stream, jd_file.filename)
        
        if not resume_text or not jd_text:
            return jsonify({"error": "Could not extract text from files"}), 400
        
        # Calculate scores
        overall, skills, exp, keywords, summary = calculate_match_score(resume_text, jd_text)
        
        prompt = f"""Tailor this resume to match the job description. Rewrite the summary and bullet points to include relevant keywords and skills from the JD. Keep it professional and concise. Return only the tailored resume text.

**Job Description:**
{jd_text}

**Original Resume:**
{resume_text}

**Tailored Resume:**"""
        
        response = model.generate_content(prompt)
        tailored = response.text.replace('```', '').strip()
        
        return jsonify({
            "customized_resume": tailored,
            "resume_text": resume_text,
            "jd_text": jd_text,
            "overall_score": overall,
            "skills_match": skills,
            "experience_match": exp,
            "keywords_match": keywords,
            "match_summary": summary
        })
    except Exception as e:
        logging.error(f"Error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/prepare-interview', methods=['POST'])
def prepare_interview():
    """Generate interview questions"""
    if not model:
        return jsonify({"error": "Model not available"}), 500
    
    data = request.json
    resume_text = data.get('resume_text')
    jd_text = data.get('jd_text')
    
    if not resume_text or not jd_text:
        return jsonify({"error": "Missing data"}), 400
    
    prompt = f"""Generate 10 likely interview questions for this job. Organize into 3 categories:

1. **Behavioral Questions** (3 questions)
2. **Technical/Skill-Based Questions** (4 questions)  
3. **Role-Specific Questions** (3 questions)

Be specific to the resume and job description.

**Job Description:**
{jd_text}

**Resume:**
{resume_text}"""
    
    try:
        response = model.generate_content(prompt)
        return jsonify({"questions": response.text})
    except Exception as e:
        logging.error(f"Error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/chat', methods=['POST'])
def chat_with_bot():
    """Chat with AI about resume"""
    if not model:
        return jsonify({"error": "Model not available"}), 500
    
    data = request.json
    resume_text = data.get('resume_text')
    history = data.get('history', [])
    user_message = data.get('message')
    
    if not resume_text or not user_message:
        return jsonify({"error": "Missing data"}), 400
    
    system_prompt = f"""You are a helpful resume coach. Answer questions about this resume and provide actionable feedback.

**Resume:**
{resume_text}

Be concise, professional, and specific."""
    
    full_prompt = system_prompt + "\n\nConversation:\n"
    for turn in history:
        full_prompt += f"{turn['role'].title()}: {turn['content']}\n"
    full_prompt += f"\nUser: {user_message}\nAssistant:"
    
    try:
        response = model.generate_content(full_prompt)
        return jsonify({"reply": response.text})
    except Exception as e:
        logging.error(f"Error: {e}")
        return jsonify({"error": str(e)}), 500
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
