# 자유게시판 운영과 복구

게시판은 Flask와 SQLite를 사용한다. 배포 코드는 /opt/finance-board/current, 운영 DB는 /var/lib/finance-board/board.sqlite에 둔다. 홈페이지 메뉴가 board.finance-fixer.net을 가리킨다. 같은 호스트에서 cloudflared가 /run/finance-board-web.sock으로 연결한다.

## 인증과 백업

systemd는 앱에 세션 서명 키(board.key)와 작성자 식별 키(identity.key)를 별도 전달한다. 세션 키를 회전할 때 작성자 식별 키는 유지한다. DB에는 식별 키의 지문이 기록되어 다른 키를 사용하면 기동이 중단된다. 공개 개설 전의 운영자 초기 글만 있는 저장소에는 최초 키를 등록할 수 있다. 지문 없는 저장소에 사용자 글·댓글·차단 정보가 있으면 시작을 중단하며, 확인된 원본에서 복구해야 한다. 메일 자격증명은 전송 전용 서비스에만 전달한다.

매일 03시 35분(한국 시간)에 SQLite 백업을 만들고 최근 7일분을 /var/lib/finance-board-backup에 보관한다. 백업에서는 로그인 세션과 미사용 인증번호를 제거한다. /etc/finance-board의 비밀키는 DB와 분리하여 권한 0600으로 보관하고, 복구용 키는 /var/backups/finance-board-keys에 별도로 둔다.

## 복구

1. 선택한 스냅샷을 별도 디렉터리로 복사하여 무결성, 글 수, 식별 키 지문을 확인한다. 백업 날짜 이후 글·삭제·차단 변경분의 복구 가능 여부를 확인한다.
2. 백업 타이머와 finance-board-web.socket, finance-board.service를 멈춘다. 이미 실행 중인 finance-board-backup.service도 종료되었는지 확인한 뒤 복구를 시작한다. 복구에 쓸 사본은 이 과정 전에 별도 위치에 복사해 둔다. 현재 DB 및 같은 이름의 WAL·SHM 파일을 한꺼번에 별도 보호 경로에 보관한다.
3. 확인한 DB 사본을 finance-board 사용자 소유, 0600 권한으로 설치한다. 스냅샷에 대응하는 identity.key를 복구한다. 이전 방식으로 만든 사본에는 로그인 세션과 OTP가 들어 있을 수 있으므로 서비스 기동 전에 sessions와 challenges를 비운다.
4. 서비스·소켓·백업 타이머를 재개한다. 운영자와 작성자가 이메일을 새로 인증하고 권한별 목록·비밀글·차단이 맞는지 확인한다.
