@echo off
setlocal
title 智能财富管家 - 一键启动

rem ============================================================
rem  智能财富管家系统一键启动：
rem    1. docker compose 拉起 MySQL / Redis / etcd / MinIO / Milvus / Neo4j
rem    2. 后端 FastAPI  （conda 环境 wealth-backend, http://127.0.0.1:8000）
rem    3. 客户端前端    （vite, http://localhost:5173）
rem    4. 内部端前端    （vite, http://localhost:5174）
rem
rem  本文件以 GBK 编码保存（中文 Windows cmd 的原生编码），勿转存为 UTF-8。
rem
rem  测试账号（密码统一 Test@1234）：
rem    内部端: advisor1 / manager1 / manager2 / risk1
rem    客户端: wangc1 / lisic2 / zhangc3 / zhaoc4 / qianc5
rem ============================================================

set "ROOT=%~dp0"
set "CONDA_ENV=wealth-backend"
set "BACKEND_PYTHON=%USERPROFILE%\.conda\envs\%CONDA_ENV%\python.exe"

if not exist "%BACKEND_PYTHON%" (
    echo [错误] 未找到 conda 环境 %CONDA_ENV% 的解释器：
    echo     %BACKEND_PYTHON%
    echo 请先执行: conda create -n %CONDA_ENV% python=3.12 并安装 backend 依赖。
    pause
    exit /b 1
)

echo [1/3] 校验后端依赖（缺失时自动安装，首次需要联网）...
pushd "%ROOT%backend"
"%BACKEND_PYTHON%" -m scripts.check_deps --install
if errorlevel 1 (
    popd
    echo [错误] 后端依赖未就绪，请检查网络后重试，或手动执行：
    echo     "%BACKEND_PYTHON%" -m pip install -e "%ROOT%backend"
    pause
    exit /b 1
)
popd

docker info >nul 2>&1
if errorlevel 1 (
    echo [错误] Docker 未运行，请先启动 Docker Desktop。
    pause
    exit /b 1
)

echo [2/3] 启动基础设施容器并等待健康检查通过...
pushd "%ROOT%"
docker compose up -d --wait --wait-timeout 180
if errorlevel 1 (
    echo [错误] docker compose 启动失败，请查看上方输出。
    popd
    pause
    exit /b 1
)
popd

echo [3/3] 拉起后端与两个前端（各自独立窗口）...
rem BACKEND_PYTHON 设在本窗口，由子进程继承，dev-backend.mjs 据此选 conda 解释器。
set "BACKEND_PYTHON=%BACKEND_PYTHON%"
start "backend-8000" cmd /k "cd /d "%ROOT%" && pnpm dev:backend"
start "customer-5173" cmd /k "cd /d "%ROOT%" && pnpm dev:customer"
start "internal-5174" cmd /k "cd /d "%ROOT%" && pnpm dev:internal"

echo.
echo 全部窗口已拉起，后端就绪（约 10 秒）后可访问：
echo   客户端    http://localhost:5173
echo   内部端    http://localhost:5174
echo   后端 API  http://127.0.0.1:8000/docs
echo.
echo 测试账号（密码均为 Test@1234）：
echo   内部端: advisor1(理财顾问)  manager1/manager2(客户经理)  risk1(风控专员)
echo   客户端: wangc1  lisic2  zhangc3  zhaoc4  qianc5
echo.
echo 停止方式：关闭三个子窗口后，在项目根目录执行 docker compose stop。
echo.
echo 本窗口将在 5 秒后自动关闭（按任意键可立即关闭）...
timeout /t 5 /nobreak >nul
endlocal
exit /b 0
