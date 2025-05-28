import os
import tempfile
from fastapi import Body, FastAPI, UploadFile, File, HTTPException, Depends
from fastapi.responses import FileResponse, JSONResponse
from typing import List, Optional
from fastapi.middleware.cors import CORSMiddleware
from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor, AutoTokenizer, AutoModelForSeq2SeqLM
from pyaspeller import YandexSpeller
import torch
import torchaudio
import json
from pydantic import BaseModel, Field
import asyncpg
from typing import Optional
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_gigachat.chat_models import GigaChat
import mysql.connector
from mysql.connector import pooling
import asyncmy
from asyncmy import connect, Pool
import requests
from doc.LoadData import load_protocol_data
from doc.PrintProtocol import create_protocol

app = FastAPI()

origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

speller = YandexSpeller()

MODEL_NAME = "bond005/wav2vec2-large-ru-golos"
processor = Wav2Vec2Processor.from_pretrained(MODEL_NAME)
model = Wav2Vec2ForCTC.from_pretrained(MODEL_NAME)

giga = GigaChat(
    credentials="",
    verify_ssl_certs=False,
)

def make_text_better(text: str):
    messages = [
        HumanMessage(content=f"""\
        Исправь все ошибки в тексте и улучши пунктуацию. НЕ МЕНЯЙ СТРУКТУРУ ТЕКСТА.
        Текст:
        {text}
        """)
    ]
    res = giga.invoke(messages)
    messages.append(res)
    print("GigaChat: ", res.content)
    return res.content

def category_text(text: str):
    messages = [
        HumanMessage(content=f"""\
        Перечисли ВСЕ основные вопросы совещания, указанные в тексте, строго в следующем формате, без лишней нумерации:
        [список основных вопросов].
        Текст:
        {text}
        """)
    ]
    res = giga.invoke(messages)
    messages.append(res)
    print("GigaChat: ", res.content)
    return res.content

def get_text_info(text: str):
    messages = [
        HumanMessage(content=f"""\
        Сгенерируй краткий заголовок (3-5 слов) и описание (1 предложение) для текста совещания. 
        Формат вывода строго:
        Заголовок: [здесь название]
        Описание: [здесь описание]
        Требования:
        1. Только факты из текста, без интерпретаций
        2. Используй ключевые темы обсуждения
        3. Без дополнительных символов (*, - и т.д.)
        4. Не включай оригинальный текст в ответ
        5. Язык сохраняй как в оригинале
        Сам текст:
        {text}
        """)
    ]
    res = giga.invoke(messages)
    messages.append(res)
    print("GigaChat: ", res.content)
    return res.content

@app.post("/recognize")
async def recognize_speech(
    audio_file: UploadFile = File(...),
    language: Optional[str] = "ru",
    sampling_rate: Optional[int] = 16000
):
    if not audio_file.filename.lower().endswith(('.wav', '.mp3', '.ogg', '.flac')):
        raise HTTPException(status_code=400, detail="Unsupported file format")

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_audio:
            content = await audio_file.read()
            temp_audio.write(content)
            temp_audio_path = temp_audio.name

        waveform, sr = torchaudio.load(temp_audio_path)

        if sr != sampling_rate:
            resampler = torchaudio.transforms.Resample(orig_freq=sr, new_freq=sampling_rate)
            waveform = resampler(waveform)

        if waveform.shape[0] > 1:
            waveform = torch.mean(waveform, dim=0, keepdim=True)

        input_values = processor(
            waveform.squeeze().numpy(),
            return_tensors="pt",
            sampling_rate=sampling_rate
        ).input_values

        with torch.no_grad():
            logits = model(input_values).logits

        predicted_ids = torch.argmax(logits, dim=-1)
        transcription = processor.batch_decode(predicted_ids)[0]

        corrected = make_text_better(transcription)

        os.unlink(temp_audio_path)
        return JSONResponse(content={
            "status": "success",
            "text": corrected,
            "raw_text": transcription,
            "language": language
        })

    except Exception as e:
        if 'temp_audio_path' in locals() and os.path.exists(temp_audio_path):
            os.unlink(temp_audio_path)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/optimize")
async def optimize_text(
    new_text: str = Body(..., media_type="text/plain")
):
    try:
        corrected = category_text(new_text)

        return JSONResponse(content={
            "status": "success",
            "text": corrected,
        })

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/info")
async def get_info(
    new_text: str = Body(..., media_type="text/plain")
):
    try:
        corrected = get_text_info(new_text)

        return JSONResponse(content={
            "status": "success",
            "text": corrected,
        })

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
class UserCreate(BaseModel):
    name: str
    surname: str
    patronomic: Optional[str] = None
    role_id: int
    telephone: str
    email: str
    password: str

class UserResponse(BaseModel):
    id: int
    name: str
    surname: str
    patronomic: Optional[str] = None
    role_id: int
    telephone: str
    email: str
    
class SubthemeCreate(BaseModel):
    name: str
    description: Optional[str] = None
    type_id: int = 1
    user_ids: List[int] = Field(default_factory=list)

class SubthemeResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    type_id: int
    users: List[UserResponse] = Field(default_factory=list)

class ConferenceCreate(BaseModel):
    name: str
    description: Optional[str] = None
    categories: List[int] = [1]
    subthemes: List[SubthemeCreate] = []
    original_text: str
    improved_text: str

class QueryYandex(BaseModel):
    id: str
    key: str

class TrackerBoardCreate(BaseModel):
    conferenceData: ConferenceCreate
    query: QueryYandex

class TrackerColsCreate(BaseModel):
    subthemes: List[SubthemeCreate] = []
    query: QueryYandex

class ConferenceRequest(BaseModel):
    name: str

MYSQL_CONFIG = {
    "host": "koyltoh4.beget.tech",
    "user": "koyltoh4_let",
    "password": "%WBUax5Bn8UG",
    "database": "koyltoh4_let",
    "port": 3306
}

async def get_db_pool():
    return await asyncmy.create_pool(
        host=MYSQL_CONFIG['host'],
        user=MYSQL_CONFIG['user'],
        password=MYSQL_CONFIG['password'],
        db=MYSQL_CONFIG['database'],
        port=MYSQL_CONFIG['port']
    )

@app.post("/conferences/")
async def create_conference(conference_data: ConferenceCreate):
    try:
        async with await get_db_pool() as pool:
            async with pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """INSERT INTO Conferences (name, description, original_text, improved_text)
                        VALUES (%s, %s, %s, %s)""",
                        (conference_data.name, conference_data.description, 
                         conference_data.original_text, conference_data.improved_text)
                    )
                    conference_id = cursor.lastrowid
                    
                    for category_id in conference_data.categories:
                        await cursor.execute(
                            """INSERT INTO ConferenceCategories (conference_id, category_id)
                            VALUES (%s, %s)""",
                            (conference_id, category_id)
                        )
                    
                    for subtheme in conference_data.subthemes:
                        await cursor.execute(
                            """INSERT INTO Subthemes (conference_id, name, description, type_id)
                            VALUES (%s, %s, %s, %s)""",
                            (conference_id, subtheme.name, subtheme.description, subtheme.type_id)
                        )
                        subtheme_id = cursor.lastrowid
                        
                        for user_id in subtheme.user_ids:
                            await cursor.execute(
                                """INSERT INTO UsersSubthemes (subtheme, user)
                                VALUES (%s, %s)""",
                                (subtheme_id, user_id)
                            )
                    
                    await conn.commit()
                    return {"status": "success", "conference_id": conference_id}
                    
    except asyncmy.Error as e:
        raise HTTPException(status_code=500, detail=f"MySQL error: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/conferences/{conference_id}")
async def get_conference(conference_id: int):
    try:
        async with await get_db_pool() as pool:
            async with pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """SELECT id, name, description, original_text, improved_text 
                           FROM Conferences WHERE id = %s""",
                        (conference_id,)
                    )
                    conference = await cursor.fetchone()
                    
                    if not conference:
                        raise HTTPException(status_code=404, detail="Conference not found")
                    
                    await cursor.execute(
                        """SELECT id, name, description, type_id 
                           FROM Subthemes WHERE conference_id = %s""",
                        (conference_id,)
                    )
                    subthemes = []
                    columns = [col[0] for col in cursor.description]
                    
                    for row in await cursor.fetchall():
                        subtheme = dict(zip(columns, row))
                        subtheme_id = subtheme['id']
                        
                        await cursor.execute(
                            """SELECT u.id, u.name, u.surname, u.patronomic, 
                                      u.role_id, u.telephone, u.email
                               FROM Users u
                               JOIN UsersSubthemes su ON u.id = su.user
                               WHERE su.subtheme = %s""",
                            (subtheme_id,)
                        )
                        user_columns = [col[0] for col in cursor.description]
                        users = [dict(zip(user_columns, row)) for row in await cursor.fetchall()]
                        
                        subtheme['users'] = users
                        subthemes.append(subtheme)
                    
                    return {
                        "conference": {
                            "id": conference[0],
                            "name": conference[1],
                            "description": conference[2],
                            "original_text": conference[3],
                            "improved_text": conference[4]
                        },
                        "subthemes": subthemes
                    }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/conferences/{conference_id}")
async def update_conference(conference_id: int, conference_data: ConferenceCreate):
    try:
        async with await get_db_pool() as pool:
            async with pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """UPDATE Conferences 
                        SET name = %s, description = %s,
                            original_text = %s, improved_text = %s
                        WHERE id = %s""",
                        (conference_data.name, conference_data.description,
                         conference_data.original_text, conference_data.improved_text,
                         conference_id)
                    )
                    
                    await cursor.execute(
                        "SELECT id FROM Subthemes WHERE conference_id = %s",
                        (conference_id,)
                    )
                    old_subtheme_ids = [row[0] for row in await cursor.fetchall()]
                    new_subtheme_ids = []
                    
                    for subtheme in conference_data.subthemes:
                        if hasattr(subtheme, 'id') and subtheme.id:
                            await cursor.execute(
                                """UPDATE Subthemes 
                                SET name = %s, description = %s, type_id = %s
                                WHERE id = %s""",
                                (subtheme.name, subtheme.description, subtheme.type_id, subtheme.id)
                            )
                            subtheme_id = subtheme.id
                        else:
                            await cursor.execute(
                                """INSERT INTO Subthemes 
                                (conference_id, name, description, type_id)
                                VALUES (%s, %s, %s, %s)""",
                                (conference_id, subtheme.name, subtheme.description, subtheme.type_id)
                            )
                            subtheme_id = cursor.lastrowid
                        
                        new_subtheme_ids.append(subtheme_id)
                        
                        await cursor.execute(
                            "DELETE FROM UsersSubthemes WHERE subtheme = %s",
                            (subtheme_id,)
                        )
                        
                        for user_id in subtheme.user_ids:
                            await cursor.execute(
                                """INSERT INTO UsersSubthemes (subtheme, user)
                                VALUES (%s, %s)""",
                                (subtheme_id, user_id)
                            )
                    
                    for old_id in old_subtheme_ids:
                        if old_id not in new_subtheme_ids:
                            await cursor.execute(
                                "DELETE FROM Subthemes WHERE id = %s",
                                (old_id,)
                            )
                    
                    await conn.commit()
                    return {"status": "success", "conference_id": conference_id}
                    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/conferences/")
async def get_conferences_list():
    try:
        async with await get_db_pool() as pool:
            async with pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """SELECT id, name, description 
                           FROM Conferences 
                           ORDER BY id DESC"""
                    )
                    
                    columns = [col[0] for col in cursor.description]
                    conferences = [
                        dict(zip(columns, row))
                        for row in await cursor.fetchall()
                    ]
                    
                    return {"conferences": conferences}
                    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/roles/")
async def get_roles():
    try:
        async with await get_db_pool() as pool:
            async with pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute("SELECT id, name FROM Roles")
                    columns = [col[0] for col in cursor.description]
                    roles = [dict(zip(columns, row)) for row in await cursor.fetchall()]
                    return {"roles": roles}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/users/")
async def get_users():
    try:
        async with await get_db_pool() as pool:
            async with pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute("""
                        SELECT u.id, u.name, u.surname, u.patronomic, u.role_id, 
                               u.telephone, u.email, r.id as role_id
                        FROM Users u
                        LEFT JOIN Roles r ON u.role_id = r.id
                    """)
                    columns = [col[0] for col in cursor.description]
                    users = [dict(zip(columns, row)) for row in await cursor.fetchall()]
                    return {"users": users}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/users/")
async def create_user(user: UserCreate):
    try:
        async with await get_db_pool() as pool:
            async with pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """INSERT INTO Users 
                        (name, surname, patronomic, role_id, telephone, email, password)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                        (user.name, user.surname, user.patronomic, user.role_id,
                         user.telephone, user.email, user.password)
                    )
                    user_id = cursor.lastrowid
                    await conn.commit()
                    return {"status": "success", "user_id": user_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/tracker_board/")
async def create_yandex_tracker(board_data: TrackerBoardCreate):
    print(board_data)
    base_url = 'https://api.tracker.yandex.net'
    endpoint = '/v3/boards/'
    headers = {
        'Authorization': f'OAuth y0__xC63MaQCBikgDggib7CoxNWkkFVXzWwBfE7eoXx_vKh2I9Pwg',
        'Content-Type': 'application/json',
        'X-Org-ID': '8236169'
    }

    payload = {
        "name": board_data.conferenceData.name,
        "defaultQueue": {
            "id": board_data.query.id,
            "key": board_data.query.key
        },
        "boardType": "default",
        # "filter": {
        #     "assignee": "USER_ID",
        #     "priority": ["normal", "high"]
        # },
        # "orderBy": "created",
        # "orderAsc": False,
        "useRanking": True,
        "country": {
            "id": "1"
        }
    }

    try:
        response = requests.post(base_url + endpoint, headers=headers, data=json.dumps(payload))

        if response.status_code == 201:
            print("Доска создана успешно!")
            board_id = response.json().get('id')
            
            await create_yandex_task(board_data)
            print(json.dumps(response.json(), indent=4, ensure_ascii=False))
            return {"status": "success"}
        elif response.status_code == 400 or response.status_code == 422:
            print("Ошибка валидации запроса. Проверьте параметры.", response.json())
        elif response.status_code == 403:
            print("Недостаточно прав для выполнения операции.")
        elif response.status_code == 404:
            print("Запрашиваемый ресурс не найден.")
        elif response.status_code == 500:
            print("Внутренняя ошибка сервера. Повторите попытку позже.")
        else:
            print(f"Произошла неизвестная ошибка ({response.status_code}). Ответ сервера: {response.text}")
        return {"status": "fail"}
    except requests.RequestException as e:
        print(f"Ошибка соединения: {e}")
        return {"status": "error"}

async def create_yandex_cols(board_data: TrackerBoardCreate, board_id: int):
    base_url = f'https://api.tracker.yandex.net/v3/boards/{board_id}/columns/'
    headers = {
        'Authorization': f'OAuth y0__xC63MaQCBikgDggib7CoxNWkkFVXzWwBfE7eoXx_vKh2I9Pwg',
        'Content-Type': 'application/json',
        'X-Org-ID': '8236169'
    }

    try:
        for i in board_data.conferenceData.subthemes:
            payload = {
                "name": i.name,
                "statuses": ["open"]
            }
            response = requests.post(base_url, headers=headers, data=json.dumps(payload))

            if response.status_code == 201:
                print("Колонка создана успешно!")
                
                print(json.dumps(response.json(), indent=4, ensure_ascii=False))
            elif response.status_code == 400 or response.status_code == 422:
                print("Ошибка валидации запроса. Проверьте параметры.", response.json())
                return {"status": "fail"}
            elif response.status_code == 403:
                print("Недостаточно прав для выполнения операции.")
                return {"status": "fail"}
            elif response.status_code == 404:
                print("Запрашиваемый ресурс не найден.")
                return {"status": "fail"}
            elif response.status_code == 500:
                print("Внутренняя ошибка сервера. Повторите попытку позже.")
                return {"status": "fail"}
            else:
                print(f"Произошла неизвестная ошибка ({response.status_code}). Ответ сервера: {response.text}")
                return {"status": "fail"}

        return {"status": "success"}
    except requests.RequestException as e:
        print(f"Ошибка соединения: {e}")
        return {"status": "error"}
    
async def create_yandex_task(board_data: TrackerBoardCreate):
    base_url = f'https://api.tracker.yandex.net/v3/issues/'
    headers = {
        'Authorization': f'OAuth y0__xC63MaQCBikgDggib7CoxNWkkFVXzWwBfE7eoXx_vKh2I9Pwg',
        'Content-Type': 'application/json',
        'X-Org-ID': '8236169'
    }

    try:
        for i in board_data.conferenceData.subthemes:
            payload = {
                "summary": i.name,
                "description": i.description,
                "queue": {
                    "id": board_data.query.id,
                    "key": board_data.query.key
                },
            }
            response = requests.post(base_url, headers=headers, data=json.dumps(payload))

            if response.status_code == 201:
                print("Задача создана успешно!")
                
                print(json.dumps(response.json(), indent=4, ensure_ascii=False))
            elif response.status_code == 400 or response.status_code == 422:
                print("Ошибка валидации запроса. Проверьте параметры.", response.json())
                return {"status": "fail"}
            elif response.status_code == 403:
                print("Недостаточно прав для выполнения операции.")
                return {"status": "fail"}
            elif response.status_code == 404:
                print("Запрашиваемый ресурс не найден.")
                return {"status": "fail"}
            elif response.status_code == 500:
                print("Внутренняя ошибка сервера. Повторите попытку позже.")
                return {"status": "fail"}
            else:
                print(f"Произошла неизвестная ошибка ({response.status_code}). Ответ сервера: {response.text}")
                return {"status": "fail"}

        return {"status": "success"}
    except requests.RequestException as e:
        print(f"Ошибка соединения: {e}")
        return {"status": "error"}
    
@app.post("/download_doc")
async def download_file(request: ConferenceRequest):
    name = request.name
    print(name)
    try:
        async with await get_db_pool() as pool:
            async with pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "SELECT id FROM Conferences WHERE name = %s",
                        (name,)
                    )
                    
                    result = await cursor.fetchone()
                    
                    if not result:
                        raise HTTPException(status_code=404, detail="Конференция не найдена")
                    
                    conference_id = result[0]
                    
                    protocol_data = create_protocol(conference_id, db_config=MYSQL_CONFIG)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
    return FileResponse(
        path=protocol_data,
        filename=os.path.basename(protocol_data),
        media_type='docx',
    )
    
@app.post("/telegram/")
async def bot_notificate():
    # notificate()
    return {"status": "success"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)

