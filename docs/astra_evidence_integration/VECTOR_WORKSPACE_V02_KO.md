# V02 실행과 원본 고정
V01 6c0d3e4 이후 Primary A에 canonical 탐색을 연결했다. 권한 확인 후 현재 발행 catalog와 최초 목록 catalog를 비교하며, 다른 발행은 409로 응답한다. 완료 bundle 선택과 optional pathway 오류를 분리했다. Scatter 원본 다운로드는 같은 descriptor에서 전체 SHA 및 전송 chunk를 검증한다. TSV 재작성과 pathname 교체를 별도로 검증했다.
Scatter·Explorer·SF API 관련 테스트 18개 통과. 다음 V03은 exact feature 선택과 표시를 연결한다.
