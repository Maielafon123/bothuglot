import pdfplumber
import json
import re
import os
from typing import List, Dict

class PDFParser:
    def __init__(self):
        self.current_dir = os.path.dirname(os.path.abspath(__file__))
        self.output_dir = os.path.join(self.current_dir, "..", "data")
        os.makedirs(self.output_dir, exist_ok=True)

    def clean_text(self, text: str) -> str:
        """Очистка текста от лишних пробелов и переносов"""
        if not text:
            return ""
        return re.sub(r'\s+', ' ', text).strip()

    def parse_options(self, cell: str) -> List[str]:
        """Извлечение вариантов ответов"""
        options = []
        if cell:
            for line in cell.split('\n'):
                if re.match(r'^\d+\)', line):
                    cleaned = self.clean_text(line.split(')')[1])
                    options.append(cleaned)
        return options

    def parse_correct_answer(self, cell: str) -> str:
        """Извлечение правильного ответа"""
        match = re.search(r'Ответ:\s*([A-E1-5]+)', cell)
        return match.group(1) if match else ""

    def process_row(self, row: List[str]) -> Dict:
        """Обработка строки таблицы"""
        try:
            if len(row) < 6:
                return None

            question_id = self.clean_text(row[0])
            if not question_id:
                return None

            return {
                "id": question_id,
                "section": self.clean_text(row[1]),
                "topic": self.clean_text(row[2]),
                "question": self.clean_text(row[3]),
                "options": self.parse_options(row[4]),
                "correct": self.parse_correct_answer(row[4]),
                "explanation": self.clean_text(row[5]),
                "reference": self.clean_text(row[6])
            }
        except Exception as e:
            print(f"Ошибка обработки строки: {row}\n{str(e)}")
            return None

    def merge_multiline_questions(self, questions: List[Dict]) -> List[Dict]:
        """Объединение многострочных вопросов"""
        merged = []
        current_question = None
        
        for q in questions:
            if q['id']:
                if current_question:
                    merged.append(current_question)
                current_question = q
            else:
                if current_question:
                    current_question['question'] += " " + q['question']
                    current_question['explanation'] += " " + q['explanation']
        if current_question:
            merged.append(current_question)
        return merged

    def parse_pdf(self, pdf_path: str) -> List[Dict]:
        """Основная функция парсинга"""
        questions = []
        
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                
                for table in tables:
                    for row in table[1:]:  # Пропуск заголовка
                        question = self.process_row(row)
                        if question:
                            questions.append(question)
        
        return self.merge_multiline_questions(questions)

    def save_to_json(self, data: List[Dict], filename: str):
        """Сохранение результатов в JSON"""
        output_path = os.path.join(self.output_dir, filename)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def run(self, input_filename: str, output_filename: str):
        """Запуск парсера"""
        input_path = os.path.join(self.current_dir, "..", "data", input_filename)
        
        if not os.path.exists(input_path):
            raise FileNotFoundError(f"PDF файл не найден: {input_path}")
        
        print(f"Начало обработки файла: {input_filename}")
        questions = self.parse_pdf(input_path)
        self.save_to_json(questions, output_filename)
        print(f"Успешно обработано вопросов: {len(questions)}")
        print(f"Результаты сохранены в: {output_filename}")

if __name__ == "__main__":
    parser = PDFParser()
    parser.run(
        input_filename="07-2-2r-dlpfgr.pdf",
        output_filename="questions.json"
    )