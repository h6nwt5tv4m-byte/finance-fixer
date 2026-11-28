# 회계법인 비교표 자동 갱신

상시 맥미니의 LaunchAgent `net.finance-fixer.accounting-firms`가 매일 한국시간 09:40 및 로그인 시 확인한다. 공단의 최신 자료생성년월까지 연속 12개월을 합산한다. DART F004는 2025년부터 수집한 법인별 최신 결산을 선택하고 같은 결산의 정정을 반영한다. 원천·검산 오류 시 운영 파일을 유지한다.

미니의 `~/.local/share/accounting-firms-refresh/`에 전용 venv, 모드 0600의 `dart.key`, 게시 실행기 `schedule.py`, 비공개 원천 캐시와 `run.log`가 있다. 의존성은 같은 폴더의 Python 3.13 가상환경에 `requirements.txt`로 설치한다. 수집·출력 코드는 매회 홈페이지 main의 격리된 사본에서 실행한다. 별도 실행기나 plist 변경 시 미니에도 복사하고 LaunchAgent를 다시 등록한다.

수동 재실행은 미니에서 `launchctl kickstart gui/$(id -u)/net.finance-fixer.accounting-firms`로 한다. 실행 결과와 마지막 종료 코드는 `launchctl print gui/$(id -u)/net.finance-fixer.accounting-firms`와 run.log에서 확인한다. 변경된 경우에만 JSON·엑셀·페이지를 같은 커밋으로 main에 올리고 실제 서비스의 고정 주소와 같은 버전의 보관본까지 대조한다. 게시 실패 시 현재 main을 확인하고 Pages 배포를 한 번 더 요청한다. 이미 열린 표의 다운로드는 그때의 버전으로 유지한다. 복구할 때는 LaunchAgent를 먼저 bootout한 뒤 해당 배포 커밋만 revert한다.
