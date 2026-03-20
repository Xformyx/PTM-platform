# PTM-platform: 버전 관리 전략 가이드

**문서 버전: 1.0**

**작성일: 2026년 3월 12일**

## 1. 개요

이 문서는 PTM-platform의 다중 서비스 아키텍처에 적합한 버전 관리 전략을 정의합니다. PTM-platform은 `api-server`, `frontend`, `workers` 등 다수의 서비스가 `docker-compose.yml`을 통해 유기적으로 연결된 **모노레포(Monorepo)** 구조를 가집니다. 이러한 구조에서는 모든 서비스가 하나의 릴리스 단위를 형성하므로, **통합 버전 관리(Unified Versioning)** 전략을 채택하는 것이 가장 효율적입니다.

이 가이드는 프로젝트 전체에 단일 버전 번호를 부여하고, Git 태그(Tag)를 활용하여 릴리스를 관리하는 방법을 제안합니다.

---

## 2. 핵심 전략: Semantic Versioning과 Git 태그

PTM-platform은 **시맨틱 버저닝(Semantic Versioning, SemVer)** [1]을 따르는 통합 버전 번호를 사용합니다. 버전은 **`MAJOR.MINOR.PATCH`** 형식으로 구성됩니다.

> **시맨틱 버저닝이란?**
> 버전 번호에 의미를 부여하여, 버전 번호만으로도 변경 사항의 성격을 예측할 수 있게 하는 규칙 체계입니다.

- **`MAJOR`**: 기존 버전과 호환되지 않는 **중대한 변경**이 있을 때 올립니다. (예: API의 요청/응답 구조 변경, 데이터베이스 스키마의 대대적인 수정 등)
- **`MINOR`**: 기존 버전과 **호환되면서 새로운 기능이 추가**될 때 올립니다. (예: 새로운 분석 기능 추가, 신규 API 엔드포인트 개발 등)
- **`PATCH`**: 기존 버전과 **호환되는 버그 수정**이 있을 때 올립니다. (예: 특정 조건에서 발생하는 리포트 생성 오류 수정, UI 텍스트 오타 수정 등)

프로젝트의 공식 릴리스는 **`main`** 브랜치의 특정 커밋에 **Git 태그**를 생성하여 표시합니다. 예를 들어, `v1.2.0`이라는 태그는 PTM-platform 1.2.0 릴리스를 의미하며, 해당 시점의 모든 서비스(`api-server`, `frontend` 등)의 코드를 포함합니다.

### 2.1. 왜 통합 버전 관리인가?

- **일관성 및 명확성**: `v1.2.0` 태그 하나로 해당 버전에 포함된 모든 서비스의 상태를 명확히 알 수 있습니다. 개발, 테스트, 배포 시점에 모든 팀원이 동일한 코드베이스를 기준으로 작업하게 됩니다.
- **의존성 관리 단순화**: 각 서비스(`api-server`, `frontend` 등)가 서로 긴밀하게 연결되어 있으므로, 개별적으로 버전을 관리하면 호환성 문제가 발생할 수 있습니다. 통합 버전은 특정 릴리스에 포함된 모든 서비스가 함께 테스트되었음을 보장합니다.
- **단순한 릴리스 프로세스**: `main` 브랜치에 새로운 Git 태그를 생성하고 푸시하는 것만으로 간단하게 새 버전을 릴리스할 수 있습니다.

---

## 3. 버전 관리 및 릴리스 프로세스

아래 프로세스는 이전에 수립한 [Git 공동 개발 워크플로우](./deployment_guide.md)를 기반으로 합니다.

### 3.1. 일반 개발 (feature, fix)

- 개발자들은 `develop` 브랜치에서 `feature` 또는 `fix` 브랜치를 생성하여 작업을 진행합니다.
- 작업 완료 후 `develop` 브랜치로 Pull Request(PR)를 보내고, 코드 리뷰 후 병합합니다.
- 이 과정에서는 버전 번호를 직접 수정하거나 태그를 생성하지 않습니다.

### 3.2. 신규 버전 릴리스 절차

`develop` 브랜치에 충분한 기능이 추가되거나 중요한 버그 수정이 완료되어 새로운 버전을 출시하기로 결정했을 때, 다음 절차를 따릅니다.

**역할**: 프로젝트 리더 또는 릴리스 담당자

1.  **`develop` 브랜치를 `main` 브랜치로 병합**

    -   `develop` 브랜치의 최신 코드가 `main` 브랜치에 반영되도록 PR을 생성하고 병합합니다.

    ```bash
    # main 브랜치로 이동하여 최신 상태 유지
    git checkout main
    git pull origin main

    # develop 브랜치의 변경 사항을 main으로 병합
    git merge develop
    ```

2.  **새 버전 태그 생성**

    -   `main` 브랜치에서 `git tag` 명령어를 사용하여 새로운 버전 태그를 생성합니다. 변경 사항의 성격에 따라 `MAJOR`, `MINOR`, `PATCH` 버전을 결정합니다.

    ```bash
    # 예시: 새로운 기능이 추가된 MINOR 업데이트 (v1.1.0 -> v1.2.0)
    git tag -a v1.2.0 -m "Release 1.2.0: Add KEGG pathway analysis feature"
    ```

    - `-a` 옵션은 주석(annotation)이 있는 태그를 생성하며, `-m`으로 릴리스에 대한 설명을 추가하는 것을 권장합니다.

3.  **`main` 브랜치와 새 태그를 원격 저장소(GitHub)에 푸시**

    ```bash
    # main 브랜치의 병합 결과를 푸시
    git push origin main

    # 생성한 태그를 푸시 (v1.2.0)
    git push origin v1.2.0
    ```

이제 GitHub 리포지토리의 "Releases" 또는 "Tags" 탭에서 `v1.2.0` 릴리스를 확인할 수 있습니다. 모든 팀원은 이 태그를 기준으로 특정 버전의 코드를 조회하거나 배포할 수 있습니다.

---

## 4. Docker 이미지 버전 관리

릴리스된 Git 태그는 Docker 이미지의 태그와 동일하게 사용하여 일관성을 유지합니다.

`docker-compose.yml` 파일에서 각 서비스의 이미지 이름을 동적으로 설정할 수 있다면 좋겠지만, Docker Compose는 이를 직접 지원하지 않습니다. 따라서, CI/CD 파이프라인(예: GitHub Actions)을 구축하여 릴리스 프로세스를 자동화하는 것을 권장합니다.

### 자동화된 CI/CD 파이프라인 (권장)

- **트리거**: `main` 브랜치에 `v*.*.*` 형식의 태그가 푸시될 때 워크플로우를 실행합니다.
- **동작**:
    1.  소스 코드를 체크아웃합니다.
    2.  `api-server`, `frontend` 등 각 서비스의 Docker 이미지를 빌드합니다.
    3.  Git 태그(예: `v1.2.0`)를 사용하여 Docker 이미지에 태그를 지정합니다. (예: `xformyx/ptm-api-server:v1.2.0`, `xformyx/ptm-frontend:v1.2.0`)
    4.  태그된 이미지를 Docker Hub 또는 Private Registry에 푸시합니다.

### 수동 빌드 및 푸시 (CI/CD 부재 시)

CI/CD가 없다면, 릴리스 담당자가 로컬에서 직접 이미지를 빌드하고 푸시해야 합니다.

```bash
# 릴리스 버전 설정
export RELEASE_VERSION=v1.2.0

# API 서버 이미지 빌드 및 푸시
docker build -t xformyx/ptm-api-server:$RELEASE_VERSION ./api-server
docker push xformyx/ptm-api-server:$RELEASE_VERSION

# Frontend 이미지 빌드 및 푸시
docker build -t xformyx/ptm-frontend:$RELEASE_VERSION ./frontend
docker push xformyx/ptm-frontend:$RELEASE_VERSION

# ... (다른 서비스들도 동일하게 진행)
```

이후, 프로덕션 환경의 `docker-compose.yml` 파일에서는 `image: xformyx/ptm-api-server:v1.2.0`과 같이 특정 버전의 이미지를 사용하도록 명시하여 안정적인 배포를 보장할 수 있습니다.

---

## 5. 참고 자료

[1] Semantic Versioning 2.0.0: [https://semver.org/lang/ko/](https://semver.org/lang/ko/)
