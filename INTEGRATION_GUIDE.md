# Mekii 랜딩 페이지 통합 가이드

## 개요

이 가이드는 Manus에서 빌드한 랜딩 페이지를 기존 PTM Platform 프론트엔드(`React 18 + react-router-dom v7 + Tailwind CSS v3`)에 통합하는 방법을 설명합니다.

## 파일 구조

```
landing-page-integration/
├── Landing.tsx              ← 메인 랜딩 페이지 컴포넌트
├── INTEGRATION_GUIDE.md     ← 이 파일
└── App.tsx.patch            ← App.tsx 라우팅 수정 예시
```

## 통합 단계

### 1단계: Landing.tsx 복사

```bash
cp Landing.tsx  frontend/src/pages/Landing.tsx
```

### 2단계: Google Fonts 추가 (Sora)

`frontend/index.html`의 `<head>` 안에 추가:

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Sora:wght@400;600;700;800&display=swap" rel="stylesheet">
```

### 3단계: App.tsx 라우팅 수정

기존 `App.tsx`에서 `/` 경로를 **public route**로 추가하고, 인증된 사용자는 `/orders`로 리다이렉트합니다.

```tsx
// frontend/src/pages/LandingRedirect.tsx
import { Navigate } from "react-router-dom";
import Landing from "./Landing";
import { useAuth } from "../hooks/useAuth"; // 기존 인증 훅

export default function LandingRedirect() {
  const { isAuthenticated } = useAuth();
  
  // 이미 로그인된 사용자는 기존 앱으로 리다이렉트
  if (isAuthenticated) {
    return <Navigate to="/orders" replace />;
  }
  
  return <Landing />;
}
```

그리고 `App.tsx`의 라우트 설정에서:

```tsx
import LandingRedirect from "./pages/LandingRedirect";

// 라우트 배열에 추가 (ProtectedRoutes 바깥, 최상단에)
{
  path: "/",
  element: <LandingRedirect />,
}
```

### 4단계: 기존 Dashboard 경로 변경

기존에 `/`가 Dashboard(protected)였다면, Dashboard를 `/dashboard`로 이동:

```tsx
// 변경 전
{ path: "/", element: <ProtectedRoute><Dashboard /></ProtectedRoute> }

// 변경 후
{ path: "/dashboard", element: <ProtectedRoute><Dashboard /></ProtectedRoute> }
{ path: "/", element: <LandingRedirect /> }  // public
```

### 5단계: 확인 사항

| 항목 | 확인 |
|------|------|
| `useNavigate` import 정상 | react-router-dom v7 호환 |
| "무료 분석 시작" 클릭 → `/login` | ✅ |
| 로그인 후 `/orders`로 이동 | 기존 로그인 로직 유지 |
| 비인증 사용자 `/` 접속 → 랜딩 | ✅ |
| 인증 사용자 `/` 접속 → `/orders` | ✅ |
| CloudFront 이미지 로딩 | 외부 URL, 별도 설정 불필요 |

## Docker/Nginx 변경 사항

**변경 불필요.** 기존 SPA 설정(`try_files $uri /index.html`)이 그대로 작동합니다. 새로운 라우트는 React Router가 클라이언트 사이드에서 처리합니다.

## 주요 변경점 (wouter → react-router-dom)

| 변경 전 (wouter) | 변경 후 (react-router-dom) |
|---|---|
| `import { useLocation } from "wouter"` | `import { useNavigate } from "react-router-dom"` |
| `const [, setLocation] = useLocation()` | `const navigate = useNavigate()` |
| `setLocation("/manual")` | `navigate("/login")` |

## 의존성

Landing.tsx는 추가 npm 패키지가 필요하지 않습니다. 기존 프로젝트의 React + react-router-dom + Tailwind CSS만 사용합니다.

## 이미지 리소스

모든 이미지는 CloudFront CDN에서 로드됩니다:
- Hero 배경: `https://d2xsxph8kpxj0f.cloudfront.net/91523048/cgED92igVd7rWrNnRft4Ln/hero-network-bg-8tAHonomEo5vKDVzkhCguq.webp`

로컬 에셋 복사는 불필요합니다.
