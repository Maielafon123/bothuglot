import os
import json
import asyncio
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import ReplyKeyboardBuilder

from sqlalchemy import create_engine, Column, Integer, String, JSON
from sqlalchemy.orm import sessionmaker, declarative_base

load_dotenv()
TOKEN = os.getenv("TOKEN")

Base = declarative_base()

class UserProgress(Base):
    __tablename__ = 'user_progress'
    user_id = Column(Integer, primary_key=True)
    level = Column(String)
    correct_answers = Column(JSON, default=dict)
    completed_tests = Column(Integer, default=0)
    weak_topics = Column(JSON, default=list)

engine = create_engine('sqlite:///english_bot.db')
Session = sessionmaker(bind=engine)
Base.metadata.create_all(engine)

class TestingState(StatesGroup):
    IN_TEST = State()
    WAITING_ANSWER = State()

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

def load_questions():
    try:
        with open('data/questions.json', 'r', encoding='utf-8') as f:
            raw_data = json.load(f)
            questions = raw_data.get("questions", []) if isinstance(raw_data, dict) else raw_data
            
            def flatten(q_list):
                flat = []
                for q in q_list:
                    if "questions" in q:
                        for sub in q["questions"]:
                            new_q = sub.copy()
                            new_q.setdefault("section", q.get("section", ""))
                            flat.append(new_q)
                    else:
                        flat.append(q)
                return flat
            
            return flatten(questions)
    except Exception as e:
        print(f"Ошибка загрузки вопросов: {str(e)}")
        return []

QUESTIONS = load_questions()

@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer(
        "🇬🇧 Английский Бот\n\n"
        "Доступные команды:\n"
        "/test - Начать тестирование\n"
        "/progress - Показать прогресс\n"
        "/lessons - Получить рекомендации"
    )

@dp.message(Command("test"))
async def start_test(message: types.Message, state: FSMContext):
    if not QUESTIONS:
        await message.answer("❌ Тест временно недоступен")
        return
    
    await state.set_state(TestingState.IN_TEST)
    await state.update_data({
        'current_question': 0,
        'score': 0,
        'answers': {},
        'started_at': message.date.timestamp()
    })
    await ask_question(message, state)

async def ask_question(message: types.Message, state: FSMContext):
    data = await state.get_data()
    current = data['current_question']
    
    if current >= len(QUESTIONS):
        await message.answer("⚠️ Непредвиденная ошибка в вопросах")
        await state.clear()
        return
    
    question = QUESTIONS[current]
    builder = ReplyKeyboardBuilder()
    
    if "options" in question:
        for idx in range(len(question["options"])):
            builder.add(types.KeyboardButton(text=str(idx+1)))
        builder.adjust(3)
        options_text = "\n".join(
            f"{i+1}. {opt}" for i, opt in enumerate(question["options"])
        )
    else:
        options_text = ""
    
    await message.answer(
        f"🔹 Вопрос {current+1}/{len(QUESTIONS)}\n"
        f"Тема: {question.get('section', 'Общая')}\n\n"
        f"{question['question']}\n\n"
        f"{options_text}",
        reply_markup=builder.as_markup(resize_keyboard=True) if "options" in question else None
    )
    await state.set_state(TestingState.WAITING_ANSWER)

@dp.message(TestingState.WAITING_ANSWER)
async def handle_answer(message: types.Message, state: FSMContext):
    data = await state.get_data()
    q_idx = data['current_question']
    
    try:
        question = QUESTIONS[q_idx]
    except IndexError:
        await message.answer("❌ Ошибка в вопросах. Тест прерван.")
        await state.clear()
        return
    
    user_answer = message.text.strip().lower()
    is_correct = False
    
    if "options" in question:
        try:
            correct_idx = int(question["correct"])
            is_correct = user_answer == str(correct_idx + 1)
            explanation = f"Правильный ответ: {correct_idx+1}. {question['options'][correct_idx]}"
        except Exception as e:
            print(f"Ошибка в вопросе {q_idx}: {str(e)}")
            is_correct = False
            explanation = "Ошибка в данных вопроса"
    else:
        correct_answer = question.get("correct", "").lower()
        is_correct = user_answer == correct_answer
        explanation = f"Правильный ответ: {correct_answer}"
    
    new_data = {
        'score': data['score'] + (1 if is_correct else 0),
        'answers': {**data['answers'], str(q_idx): is_correct}
    }
    
    if q_idx + 1 < len(QUESTIONS):
        await state.update_data({**new_data, 'current_question': q_idx + 1})
        await ask_question(message, state)
    else:
        await finish_test(message, state, new_data)
        await state.clear()

    await message.answer(
        "✅ Верно!\n" + explanation if is_correct 
        else "❌ Неверно!\n" + explanation
    )

async def finish_test(message: types.Message, state: FSMContext, test_data: dict):
    try:
        score = test_data['score']
        total = len(QUESTIONS)
        
        level = "C1" if (score/total) >= 0.8 else \
                "B2" if (score/total) >= 0.6 else \
                "B1" if (score/total) >= 0.4 else "A2"
        
        weak_topics = [
            QUESTIONS[i].get('section', 'Общая') 
            for i in range(total) 
            if not test_data['answers'].get(str(i), False)
        ]
        unique_weak = list(dict.fromkeys(weak_topics))[:5]
        
        with Session() as session:
            # Исправление для SQLAlchemy 2.0
            user = session.get(UserProgress, message.from_user.id)
            if not user:
                user = UserProgress(
                    user_id=message.from_user.id,
                    level=level,
                    correct_answers=test_data['answers'],
                    completed_tests=1,
                    weak_topics=unique_weak
                )
            else:
                user.level = level
                user.correct_answers = test_data['answers']
                user.completed_tests = (user.completed_tests or 0) + 1
                user.weak_topics = unique_weak
            
            session.add(user)
            session.commit()
        
        report = (
            f"📊 Тест завершен!\n"
            f"Уровень: {level}\n"
            f"Правильных ответов: {score}/{total}\n\n"
            f"Слабые темы:\n" + 
            "\n".join(f"• {topic}" for topic in unique_weak[:3]) +
            "\n\nИспользуйте /lessons для рекомендаций"
        )
        
        await message.answer(report, reply_markup=types.ReplyKeyboardRemove())
    
    except Exception as e:
        print(f"Ошибка завершения теста: {str(e)}")
        await message.answer("⚠️ Ошибка сохранения результатов")

@dp.message(Command("progress"))
async def show_progress(message: types.Message):
    with Session() as session:
        user = session.get(UserProgress, message.from_user.id)
        
        if not user or not user.completed_tests:
            await message.answer("📭 Вы еще не проходили тест")
            return
        
        progress = (
            f"📈 Ваш прогресс:\n"
            f"Уровень: {user.level}\n"
            f"Пройдено тестов: {user.completed_tests}\n"
            f"Последний результат: {sum(user.correct_answers.values())}/{len(user.correct_answers)}\n\n"
            f"Рекомендуемые темы:\n" + 
            "\n".join(f"• {topic}" for topic in user.weak_topics[:3])
        )
        await message.answer(progress)

@dp.message(Command("lessons"))
async def recommend_lessons(message: types.Message):
    LESSONS_MAP = {
       "глагол": "https://www.englishdom.com/blog/glagoly-v-anglijskom-yazyke/",
        "артикль": "https://skyeng.ru/articles/v-chem-raznitsa-mezhdu-opredelennym-i-neopredelennym-artiklem-v-anglijskom-yazyke/",
        "прилагательное": "https://lingualeo.com/ru/blog/2023/09/19/prilagatelnye-v-anglijskom-yazyke/",
        "морфология": "https://ru.wikipedia.org/wiki/Английская_грамматика",
        "времена": "https://skyeng.ru/articles/vse-vremena-glagola-v-anglijskom-yazyke/",
        "предлог": "https://www.bkc.ru/blog/about-language/grammar/predlogi-v-angliyskom-yazyke/",
        "существительное": "https://englex.ru/english-nouns/",
        "общая": "не придумал"
    }
    
    with Session() as session:
        user = session.get(UserProgress, message.from_user.id)
        
        if not user or not user.weak_topics:
            await message.answer("❌ Сначала пройдите тест /test")
            return
        
        recommendations = []
        for topic in list(dict.fromkeys(user.weak_topics))[:3]:
            clean_topic = topic.lower()
            url = next(
                (v for k, v in LESSONS_MAP.items() if k in clean_topic),
                LESSONS_MAP['общая']
            )
            recommendations.append(f"📚 {topic}: {url}")
        
        await message.answer(
            "Рекомендуемые материалы:\n\n" + 
            "\n".join(recommendations)
        )

async def main():
    print("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())