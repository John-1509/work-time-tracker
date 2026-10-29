"""FastAPI routes. A thin layer: HTTP in, service call, HTTP out."""
from pathlib import Path

from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from app import service
from app.db import get_connection, init_db

INDEX_PAGE = Path(__file__).resolve().parent.parent / "static" / "index.html"

STATUS_BY_ERROR = {
    service.NotFound: 404,
    service.Conflict: 409,
    service.InvalidInput: 422,
}


class EmployeeIn(BaseModel):
    name: str


class TimerStartIn(BaseModel):
    task: str


def create_app(db_path: str | None = None) -> FastAPI:
    app = FastAPI(title="Work Time Tracking")
    init_db(get_connection(db_path))  # make sure the schema exists before the first request

    def get_conn():
        # One connection per request: a shared connection is not safe across threads.
        conn = get_connection(db_path)
        try:
            yield conn
        finally:
            conn.close()

    @app.exception_handler(service.ServiceError)
    async def service_error_handler(request: Request, exc: service.ServiceError):
        return JSONResponse(status_code=STATUS_BY_ERROR[type(exc)], content={"detail": str(exc)})

    @app.post("/employees", status_code=201)
    def add_employee(body: EmployeeIn, conn=Depends(get_conn)):
        return service.add_employee(conn, body.name)

    @app.get("/employees")
    def list_employees(conn=Depends(get_conn)):
        return service.list_employees(conn)

    @app.post("/employees/{employee_id}/timer/start", status_code=201)
    def start_timer(employee_id: int, body: TimerStartIn, conn=Depends(get_conn)):
        return service.start_timer(conn, employee_id, body.task)

    @app.post("/employees/{employee_id}/timer/stop")
    def stop_timer(employee_id: int, conn=Depends(get_conn)):
        return service.stop_timer(conn, employee_id)

    @app.get("/employees/{employee_id}/entries")
    def get_entries(employee_id: int, from_: str | None = Query(None, alias="from"),
                    to: str | None = None, conn=Depends(get_conn)):
        return service.get_entries(conn, employee_id, from_, to)

    @app.get("/report")
    def get_report(from_: str | None = Query(None, alias="from"),
                   to: str | None = None, conn=Depends(get_conn)):
        return service.get_report(conn, from_, to)

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(INDEX_PAGE)

    return app


app = create_app()