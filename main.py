import json
import os
import uvicorn
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import Column, Integer, String, ForeignKey, select, func
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(CURRENT_DIR, "templates") if os.path.isdir(os.path.join(CURRENT_DIR, "templates")) else CURRENT_DIR

DATABASE_URL = "sqlite+aiosqlite:///:memory:"
engine = create_async_engine(DATABASE_URL, connect_args={"check_same_thread": False})
async_session = async_sessionmaker(engine, expire_on_commit=False)
Base = declarative_base()

templates = Jinja2Templates(directory=TEMPLATES_DIR)


class Warehouse(Base):
    __tablename__ = "warehouses"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    is_active = Column(Integer, default=1)


class Stock(Base):
    __tablename__ = "stocks"
    id = Column(Integer, primary_key=True, autoincrement=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False)
    source_ff_id = Column(Integer, default=0, nullable=False)
    warehouse_name = Column(String, nullable=False)
    sku = Column(String, nullable=False)
    name = Column(String, nullable=False)

    physical_qty = Column(Integer, default=0, nullable=False)
    reserved_qty = Column(Integer, default=0, nullable=False)
    transit_qty = Column(Integer, default=0, nullable=False)
    available_qty = Column(Integer, default=0, nullable=False)

class MovementLog(Base):
    __tablename__ = "movement_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(String, nullable=False)
    action_type = Column(String, nullable=False)
    sku = Column(String, nullable=False)
    name = Column(String, nullable=False)
    qty = Column(Integer, nullable=False)
    route = Column(String, nullable=False)

def normalize_sku(sku: str) -> str:
    return sku.strip().upper()


def alert_redirect(message: str | None = None) -> HTMLResponse:
    if message:
        safe_msg = json.dumps(message, ensure_ascii=False)
        return HTMLResponse(f"<script>alert({safe_msg}); window.location.href='/';</script>")
    return HTMLResponse("<script>window.location.href='/';</script>")


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session() as session:
        warehouses = [
            Warehouse(id=1, name="Север"),
            Warehouse(id=2, name="Юг"),
            Warehouse(id=3, name="WB"),
            Warehouse(id=4, name="Ozon"),
            Warehouse(id=5, name="Яндекс.Маркет"),
            Warehouse(id=7, name="WB"),
            Warehouse(id=8, name="Ozon"),
            Warehouse(id=9, name="Яндекс.Маркет"),
        ]
        session.add_all(warehouses)

        stocks_to_add = [
            Stock(warehouse_id=1, source_ff_id=0, warehouse_name="Север", sku="SKU-101", name="Водка", physical_qty=50, reserved_qty=0, transit_qty=0, available_qty=50),
            Stock(warehouse_id=1, source_ff_id=0, warehouse_name="Север", sku="SKU-102", name="Кола", physical_qty=100, reserved_qty=0, transit_qty=0, available_qty=100),
            Stock(warehouse_id=1, source_ff_id=0, warehouse_name="Север", sku="SKU-103", name="Чипсы", physical_qty=75, reserved_qty=0, transit_qty=0, available_qty=75),
            Stock(warehouse_id=1, source_ff_id=0, warehouse_name="Север", sku="SKU-108", name="sigar", physical_qty=28, reserved_qty=0, transit_qty=0, available_qty=28),

            Stock(warehouse_id=2, source_ff_id=0, warehouse_name="Юг", sku="SKU-101", name="Водка", physical_qty=30, reserved_qty=0, transit_qty=0, available_qty=30),
            Stock(warehouse_id=2, source_ff_id=0, warehouse_name="Юг", sku="SKU-102", name="Кола", physical_qty=60, reserved_qty=0, transit_qty=0, available_qty=60),
            Stock(warehouse_id=2, source_ff_id=0, warehouse_name="Юг", sku="SKU-103", name="Чипсы", physical_qty=40, reserved_qty=0, transit_qty=0, available_qty=40),
            Stock(warehouse_id=2, source_ff_id=0, warehouse_name="Юг", sku="SKU-108", name="sigar", physical_qty=15, reserved_qty=0, transit_qty=0, available_qty=15),
        ]
        session.add_all(stocks_to_add)
        await session.commit()
    yield


app = FastAPI(title="CheckStock", lifespan=lifespan)

@app.get("/export-log")
async def export_log():
    async with async_session() as session:
        res = await session.execute(select(MovementLog).order_by(MovementLog.id.desc()))
        logs = res.scalars().all()

    lines = [
        "ЖУРНАЛ ДВИЖЕНИЯ ТОВАРОВ (CHECKSTOCK)",
        "=" * 84,
        f"{'ID':<4} | {'Дата и время':<19} | {'Операция':<16} | {'Арт.':<8} | {'Кол-во':<6} | {'Маршрут / Товар'}",
        "-" * 84
    ]
    for item in logs:
        lines.append(
            f"{item.id:<4} | {item.created_at:<19} | {item.action_type:<16} | {item.sku:<8} | {item.qty:<6} | {item.route} ({item.name})"
        )

    content = "\n".join(lines) if logs else "Журнал движений пока пуст. Оформите приход или расход товара."
    return PlainTextResponse(
        content=content,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=movement_log.txt"}
    )

async def get_db_session():
    async with async_session() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
@app.get("/", response_class=HTMLResponse)
async def index_endpoint(request: Request, db: AsyncSession = Depends(get_db_session)):
    res_stocks = await db.execute(select(Stock))
    stocks_list = res_stocks.scalars().all()

    reserved_map: dict[tuple[int, str], int] = {}
    for s in stocks_list:
        if s.warehouse_id in (3, 4, 5):
            key = (s.source_ff_id, s.sku)
            reserved_map[key] = reserved_map.get(key, 0) + s.reserved_qty

    for item in stocks_list:
        if item.warehouse_id in (1, 2):
            total_reserved = reserved_map.get((item.warehouse_id, item.sku), 0)
            item.available_qty = max(0, item.physical_qty - total_reserved)
        else:
            item.available_qty = 0

    res_wh = await db.execute(select(Warehouse))
    warehouses_list = res_wh.scalars().all()

    return templates.TemplateResponse(
        "index.html",
        {"request": request, "stocks": stocks_list, "warehouses": warehouses_list}
    )


@app.post("/stock/income")
async def income_endpoint(
    from_warehouse_id: int = Form(0),
    warehouse_id: int = Form(...),
    sku: str = Form(...),
    name: str = Form("Товар"),
    quantity: int = Form(...),
    db: AsyncSession = Depends(get_db_session)
):
    sku = normalize_sku(sku)
    normalized_input_name = " ".join(name.strip().split())
    is_default_or_empty = not normalized_input_name or normalized_input_name.casefold() == "товар"

    if not sku:
        return alert_redirect("Укажите артикул (SKU) товара!")
    if quantity <= 0:
        return alert_redirect("Количество должно быть больше 0!")
    if from_warehouse_id == warehouse_id:
        return alert_redirect("Склад-источник и склад-получатель совпадают!")

    # Проверка соответствия: 1 товар = 1 артикул по всей базе
    all_res = await db.execute(select(Stock))
    all_stocks = all_res.scalars().all()

    existing_by_sku = next((s for s in all_stocks if s.sku == sku), None)
    existing_by_name = (
        next((s for s in all_stocks if s.name.casefold() == normalized_input_name.casefold()), None)
        if not is_default_or_empty else None
    )

    if existing_by_name and existing_by_name.sku != sku:
        return alert_redirect(
            f"Товар «{existing_by_name.name}» уже закреплён за артикулом {existing_by_name.sku}. "
            f"Пожалуйста, используйте артикул {existing_by_name.sku}!"
        )

    if existing_by_sku:
        if not is_default_or_empty and existing_by_sku.name.casefold() != normalized_input_name.casefold():
            return alert_redirect(
                f"Артикул {sku} уже закреплён за товаром «{existing_by_sku.name}». "
                f"Укажите «{existing_by_sku.name}» или оставьте поле названия пустым!"
            )
        clean_name = existing_by_sku.name
    else:
        if is_default_or_empty:
            return alert_redirect(
                f"Артикул {sku} новый в системе — пожалуйста, укажите наименование товара!"
            )
        clean_name = normalized_input_name

    res = await db.execute(select(Stock).where(Stock.warehouse_id == warehouse_id, Stock.sku == sku))
    target_stock = res.scalar_one_or_none()

    if not target_stock:
        wh = await db.get(Warehouse, warehouse_id)
        wh_name = wh.name if wh else f"Склад {warehouse_id}"
        target_stock = Stock(
            warehouse_id=warehouse_id,
            source_ff_id=0,
            warehouse_name=wh_name,
            sku=sku,
            name=clean_name,
            physical_qty=0,
            reserved_qty=0,
            transit_qty=0,
            available_qty=0
        )
        db.add(target_stock)

    match from_warehouse_id:
        case 0:
            target_stock.physical_qty += quantity

        case 3 | 4 | 5:
            # Возврат строго с FBO -> списываем ТОЛЬКО из transit_qty (FBO)
            market_res = await db.execute(
                select(Stock).where(
                    Stock.warehouse_id == from_warehouse_id,
                    Stock.source_ff_id == warehouse_id,
                    Stock.sku == sku
                )
            )
            market_stock = market_res.scalar_one_or_none()

            if not market_stock or market_stock.transit_qty < quantity:
                avail_fbo = market_stock.transit_qty if market_stock else 0
                return alert_redirect(
                    f"Недостаточно товара на FBO для возврата! На FBO числится: {avail_fbo} шт."
                )

            market_stock.transit_qty -= quantity
            target_stock.physical_qty += quantity

        case 7 | 8 | 9:
            # Возврат строго с FBS -> списываем ТОЛЬКО из reserved_qty (FBS)
            market_wh_id = {7: 3, 8: 4, 9: 5}[from_warehouse_id]
            market_res = await db.execute(
                select(Stock).where(
                    Stock.warehouse_id == market_wh_id,
                    Stock.source_ff_id == warehouse_id,
                    Stock.sku == sku
                )
            )
            market_stock = market_res.scalar_one_or_none()

            if not market_stock or market_stock.reserved_qty < quantity:
                avail_fbs = market_stock.reserved_qty if market_stock else 0
                return alert_redirect(
                    f"Недостаточно товара в резерве FBS для возврата! В резерве FBS: {avail_fbs} шт."
                )

            market_stock.reserved_qty -= quantity

        case _:
            source_res = await db.execute(
                select(Stock).where(Stock.warehouse_id == from_warehouse_id, Stock.sku == sku)
            )
            source_stock = source_res.scalar_one_or_none()
            if not source_stock or source_stock.physical_qty < quantity:
                avail = source_stock.physical_qty if source_stock else 0
                return alert_redirect(f"Недостаточно остатка на складе-источнике! Доступно: {avail} шт.")

            source_stock.physical_qty -= quantity
            target_stock.physical_qty += quantity

    src_wh = await db.get(Warehouse, from_warehouse_id) if from_warehouse_id else None
    if from_warehouse_id == 0:
        src_label, op_label = "Поставщик", "Приход"
    elif from_warehouse_id in (3, 4, 5):
        src_label, op_label = f"FBO ({src_wh.name})", "Возврат с FBO"
    elif from_warehouse_id in (7, 8, 9):
        src_label, op_label = f"FBS ({src_wh.name})", "Возврат с FBS"
    else:
        src_label, op_label = (src_wh.name if src_wh else f"Склад {from_warehouse_id}"), "Перемещение"

    db.add(MovementLog(
        created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        action_type=op_label,
        sku=sku,
        name=clean_name,
        qty=quantity,
        route=f"{src_label} -> {target_stock.warehouse_name}"
    ))

    await db.commit()
    return alert_redirect()


@app.post("/stock/transfer")
async def transfer_endpoint(
    from_warehouse_id: int = Form(...),
    to_warehouse_id: int = Form(...),
    sku: str = Form(...),
    quantity: int = Form(...),
    db: AsyncSession = Depends(get_db_session)
):
    sku = normalize_sku(sku)

    if not sku:
        return alert_redirect("Укажите артикул (SKU) товара!")
    if quantity <= 0:
        return alert_redirect("Количество должно быть больше 0!")
    if from_warehouse_id == to_warehouse_id:
        return alert_redirect("Склады отправления и назначения совпадают!")

    res = await db.execute(select(Stock).where(Stock.warehouse_id == from_warehouse_id, Stock.sku == sku))
    source_stock = res.scalar_one_or_none()

    if not source_stock:
        return alert_redirect("Товар не найден на складе отправления!")

    sku_res = await db.execute(
        select(func.sum(Stock.reserved_qty)).where(
            Stock.warehouse_id.in_([3, 4, 5]),
            Stock.source_ff_id == from_warehouse_id,
            Stock.sku == sku
        )
    )
    total_market_reserved = sku_res.scalar() or 0
    current_available = source_stock.physical_qty - total_market_reserved

    if current_available < quantity:
        return alert_redirect(f"Недостаточно свободного товара! Доступно всего {current_available} шт.")

    match to_warehouse_id:
        case 3 | 4 | 5:
            operation_type = "FBO"
            target_wh_id = to_warehouse_id
        case 7:
            operation_type = "FBS"
            target_wh_id = 3
        case 8:
            operation_type = "FBS"
            target_wh_id = 4
        case 9:
            operation_type = "FBS"
            target_wh_id = 5
        case _:
            operation_type = "FF"
            target_wh_id = to_warehouse_id

    dest_source_ff = from_warehouse_id if target_wh_id in (3, 4, 5) else 0
    dest_res = await db.execute(
        select(Stock).where(
            Stock.warehouse_id == target_wh_id,
            Stock.source_ff_id == dest_source_ff,
            Stock.sku == sku
        )
    )
    dest_stock = dest_res.scalar_one_or_none()

    if not dest_stock:
        wh_target = await db.get(Warehouse, target_wh_id)
        correct_wh_name = wh_target.name if wh_target else f"Склад {target_wh_id}"
        dest_stock = Stock(
            warehouse_id=target_wh_id,
            source_ff_id=dest_source_ff,
            warehouse_name=correct_wh_name,
            sku=sku,
            name=source_stock.name,
            physical_qty=0,
            reserved_qty=0,
            transit_qty=0,
            available_qty=0
        )
        db.add(dest_stock)

    match operation_type:
        case "FF":
            source_stock.physical_qty -= quantity
            dest_stock.physical_qty += quantity
        case "FBS":
            dest_stock.reserved_qty += quantity
        case "FBO":
            source_stock.physical_qty -= quantity
            dest_stock.transit_qty += quantity

    op_map = {
        "FF": "Перемещение",
        "FBS": "Резерв FBS",
        "FBO": "Отправка FBO"
    }
    dst_label = f"{operation_type} ({dest_stock.warehouse_name})" if operation_type in ("FBS", "FBO") else dest_stock.warehouse_name
    db.add(MovementLog(
        created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        action_type=op_map.get(operation_type, operation_type),
        sku=sku,
        name=source_stock.name,
        qty=quantity,
        route=f"{source_stock.warehouse_name} -> {dst_label}"
    ))

    await db.commit()
    return alert_redirect()

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=5050)
