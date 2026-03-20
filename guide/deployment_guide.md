# PTM-platform: 배포 및 공동 개발 가이드

**문서 버전: 1.0**

**작성일: 2026년 3월 12일**

## 1. 소개

이 문서는 PTM-platform의 다중 서버 배포, 오프라인 환경에서의 설치, 그리고 2인 공동 개발을 위한 Git 워크플로우를 상세히 안내합니다. 각 개발자는 이 가이드를 따라 독립적인 개발 및 테스트 환경을 구축하고, 표준화된 절차에 따라 협업을 진행할 수 있습니다.

---

## 2. 다중 서버 배포 및 환경 설정

각 개발자는 자신의 로컬 서버(예: Mac Studio)에 PTM-platform을 독립적으로 배포하여 테스트를 수행할 수 있습니다. 아래 절차는 각 서버에서 동일하게 진행됩니다.

### 2.1. 사전 요구사항

- **Git**: 버전 관리 시스템
- **Docker & Docker Compose**: 컨테이너 실행 환경
- **Cytoscape Desktop**: 네트워크 시각화 툴 (실행 중이어야 함)

### 2.2. 프로젝트 클론

터미널을 열고 다음 명령어를 실행하여 GitHub 리포지토리를 로컬 머신으로 복제합니다.

```bash
git clone https://github.com/Xformyx/PTM-platform.git
cd PTM-platform
```

### 2.3. 환경 변수 설정 (`.env`)

프로젝트 루트 디렉토리에 `.env` 파일을 생성하고, 각 서버 환경에 맞게 아래 내용을 수정하여 입력합니다. 이 파일은 Git에서 추적하지 않으므로, 민감한 정보를 안전하게 관리할 수 있습니다.

```env
# .env

# Docker Compose 설정
COMPOSE_PROJECT_NAME=ptm_platform

# API 서버 설정
API_SERVER_PORT=8000

# Cytoscape 연결 설정
# Docker 컨테이너에서 호스트 머신(Mac Studio)의 Cytoscape에 연결하기 위한 주소
CYTOSCAPE_HOST=host.docker.internal
CYTOSCAPE_PORT=1234

# ChromaDB 데이터베이스 경로
# 호스트 머신(Mac Studio)의 실제 경로를 입력합니다.
# 이 경로는 아래 docker-compose.override.yml 파일에서 볼륨으로 마운트됩니다.
CHROMA_DB_PATH=/path/to/your/chroma/db

# GitHub 개인 접근 토큰 (Personal Access Token)
# GitHub API 접근 및 push/pull 작업에 필요
GITHUB_PAT=ghp_************************************
```

### 2.4. 로컬 환경용 Docker Compose 설정

각자의 로컬 환경에서 `docker-compose.yml`을 직접 수정하는 대신, `docker-compose.override.yml` 파일을 생성하여 개인화된 설정을 덮어씁니다. 이 파일은 Git에서 추적하지 않으므로 다른 개발자의 설정에 영향을 주지 않습니다.

프로젝트 루트에 `docker-compose.override.yml` 파일을 생성하고 아래 내용을 추가합니다.

```yaml
# docker-compose.override.yml
version: '3.8'

services:
  api-server:
    volumes:
      # .env 파일에 정의된 CHROMA_DB_PATH를 컨테이너 내부 경로로 마운트
      - ${CHROMA_DB_PATH}:/app/chroma_db
  
  gateway:
    ports:
      # 호스트 머신의 8080 포트를 컨테이너의 80 포트로 연결
      # 각 개발자는 충돌을 피하기 위해 다른 포트(예: 8081)를 사용할 수 있습니다.
      - "8080:80"
```

**설정 설명:**

- **`api-server.volumes`**: `.env` 파일에 지정한 Mac Studio의 ChromaDB 데이터 경로를 `api-server` 컨테이너 내부의 `/app/chroma_db`로 연결(마운트)합니다. 이를 통해 컨테이너가 호스트의 데이터베이스 파일을 직접 읽고 쓸 수 있습니다.
- **`gateway.ports`**: 웹 브라우저에서 `http://localhost:8080`으로 접속하면 PTM-platform 프론트엔드에 접근할 수 있도록 포트를 설정합니다. 다른 개발자와 포트가 겹칠 경우, `"8081:80"`과 같이 수정하여 사용하십시오.

### 2.5. 애플리케이션 실행

모든 설정이 완료되면, 다음 명령어를 실행하여 Docker 컨테이너를 빌드하고 실행합니다.

```bash
docker-compose up -d --build
```

이제 웹 브라우저에서 `http://localhost:8080` (또는 `docker-compose.override.yml`에 설정한 포트)으로 접속하여 PTM-platform이 정상적으로 실행되는지 확인합니다.

---

## 3. 오프라인/제한된 네트워크 환경 배포

외부 네트워크가 차단된 환경에 배포하기 위해서는 Docker 이미지를 빌드하는 시점에 모든 의존성을 포함해야 합니다. 이를 위해 인터넷이 연결된 환경에서 의존성을 미리 다운로드하고, 이를 빌드 과정에 활용합니다.

### 3.1. 오프라인 빌드 전략

1.  **의존성 다운로드**: 인터넷이 가능한 환경에서 Python (`pip`), Node.js (`npm`), 시스템 (`apt`) 의존성을 모두 로컬 디렉토리에 다운로드합니다.
2.  **Dockerfile 수정**: 다운로드한 의존성을 사용하여 빌드하도록 각 서비스의 `Dockerfile`을 수정합니다.
3.  **Docker 이미지 빌드 및 저장**: 수정된 `Dockerfile`로 이미지를 빌드한 후, `docker save` 명령어로 `.tar` 파일로 저장합니다.
4.  **오프라인 환경으로 전송 및 로드**: 저장된 `.tar` 파일을 오프라인 서버로 전송하고, `docker load` 명령어로 이미지를 로드하여 컨테이너를 실행합니다.

### 3.2. 실행 예시: `api-server` 오프라인 빌드

#### 3.2.1. 의존성 다운로드 (온라인 환경)

```bash
# /home/ubuntu/PTM-platform/workers 디렉토리에서 실행

# Python 패키지 다운로드
mkdir -p offline_packages/pip
pip download -r requirements.txt -d offline_packages/pip
```

#### 3.2.2. `workers/Dockerfile` 수정

기존 `Dockerfile`을 `Dockerfile.offline`으로 복사하고, `pip install` 부분을 수정하여 로컬 패키지를 사용하도록 변경합니다.

```dockerfile
# Dockerfile.offline (workers/)

# ... (기존 Dockerfile 내용) ...

# 오프라인 패키지 복사
COPY offline_packages/ /app/offline_packages/

# --no-index: PyPI 인덱스를 사용하지 않음
# --find-links: 로컬 디렉토리에서 패키지를 찾음
RUN pip install --no-index --find-links=/app/offline_packages/pip -r requirements.txt

# ... (이후 내용 동일) ...
```

`frontend` 및 기타 서비스도 동일한 방식으로 `npm` 패키지 캐시 등을 활용하여 오프라인 빌드가 가능하도록 수정할 수 있습니다.

---

## 4. Git 공동 개발 워크플로우

두 명의 개발자가 충돌 없이 효율적으로 협업하기 위해 `Git-flow`의 핵심 개념을 차용한 브랜치 전략을 사용합니다.

### 4.1. 브랜치 종류 및 역할

| 브랜치 종류 | 설명 |
| :--- | :--- |
| **`main`** | **제품 출시 버전**이 위치하는 가장 안정적인 브랜치. 오직 `develop` 브랜치로부터의 병합(Merge)만 허용됩니다. |
| **`develop`** | **다음 출시 버전을 개발**하는 메인 브랜치. 모든 기능 개발은 이 브랜치에서 분기(branch)하여 시작합니다. |
| **`feature/{기능이름}`** | **개별 기능을 개발**하는 브랜치. `develop`에서 분기하며, 개발 완료 후 `develop`으로 Pull Request(PR)를 보냅니다. |

### 4.2. 공동 개발 프로세스

**A 개발자가 '사용자 인증' 기능을 개발하는 시나리오:**

1.  **`develop` 브랜치 최신화**

    ```bash
    git checkout develop
    git pull origin develop
    ```

2.  **기능 브랜치 생성**

    ```bash
    # feature/user-authentication 브랜치를 생성하고 해당 브랜치로 이동
    git checkout -b feature/user-authentication
    ```

3.  **기능 개발 및 커밋**

    -   '사용자 인증' 기능 관련 코드를 수정하거나 추가합니다.
    -   작업 단위로 커밋(commit)을 남깁니다. 커밋 메시지는 아래 **4.3. 커밋 메시지 규칙**을 따릅니다.

    ```bash
    git add .
    git commit -m "feat: Add user login API endpoint"
    ```

4.  **GitHub에 브랜치 Push**

    ```bash
    git push origin feature/user-authentication
    ```

5.  **Pull Request (PR) 생성**

    -   GitHub 리포지토리 페이지로 이동하여 `feature/user-authentication` 브랜치에서 `develop` 브랜치로 향하는 PR을 생성합니다.
    -   PR 제목과 설명에 개발 내용을 명확히 기재합니다.

6.  **코드 리뷰 및 병합**

    -   **B 개발자**는 PR을 검토하고 피드백을 남깁니다.
    -   수정 사항이 반영되고, CI/CD 테스트(설정된 경우)가 통과되면 B 개발자는 PR을 `develop` 브랜치에 병합(Merge)합니다.
    -   병합 후 `feature/user-authentication` 브랜치는 삭제합니다.

### 4.3. 커밋 메시지 규칙

모든 커밋 메시지는 다음 형식을 따릅니다. 이는 커밋 히스토리의 가독성을 높이고, 변경 사항을 쉽게 추적하기 위함입니다.

**형식**: `type: subject`

-   **`type`**: 커밋의 성격을 나타내는 접두사
    -   `feat`: 새로운 기능 추가
    -   `fix`: 버그 수정
    -   `docs`: 문서 수정
    -   `style`: 코드 포맷팅, 세미콜론 누락 등 (코드 변경은 없음)
    -   `refactor`: 코드 리팩토링
    -   `test`: 테스트 코드 추가/수정
    -   `chore`: 빌드 업무, 패키지 매니저 설정 등
-   **`subject`**: 50자 이내의 간결한 설명

**예시**:

-   `feat: Add multi-condition PTM data merging system`
-   `fix: Resolve Cytoscape connection timeout issue`
-   `docs: Update deployment guide for offline environments`

### 4.4. 브랜치 네이밍 규칙

-   **`main`**, **`develop`**: 고정된 이름 사용
-   기능 브랜치: `feature/{기능 요약}` (예: `feature/report-pdf-export`)
-   버그 수정 브랜치: `fix/{문제 요약}` (예: `fix/network-node-rendering-bug`)

이 가이드라인을 통해 모든 팀원이 일관된 방식으로 프로젝트를 개발하고 배포하여 생산성을 극대화할 수 있기를 기대합니다.
