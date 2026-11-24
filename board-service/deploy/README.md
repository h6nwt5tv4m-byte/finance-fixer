# 자유게시판 운영과 복구

게시판은 Flask와 SQLite를 사용한다. 배포 코드는 /opt/finance-board/current, 운영 DB는 /var/lib/finance-board/board.sqlite에 둔다. 홈페이지 메뉴가 board.finance-fixer.net을 가리킨다. 같은 호스트에서 cloudflared가 /run/finance-board-web.sock으로 연결한다.

## 인증과 백업

systemd는 앱에 세션 서명 키(board.key)와 작성자 식별 키(identity.key)를 별도 전달한다. 세션 키를 회전할 때 작성자 식별 키는 유지한다. DB에는 식별 키의 지문이 기록되어 다른 키를 사용하면 기동이 중단된다. 공개 개설 전의 운영자 초기 글만 있는 저장소에는 최초 키를 등록할 수 있다. 지문 없는 저장소에 사용자 글·댓글·차단 정보가 있으면 시작을 중단하며, 확인된 원본에서 복구해야 한다. 메일 자격증명은 전송 전용 서비스에만 전달한다.

매일 03시 35분(한국 시간)에 SQLite 백업을 만들고 최근 7일분을 /var/lib/finance-board-backup에 보관한다. 백업에서는 로그인 세션과 미사용 인증번호를 제거한다. /etc/finance-board의 비밀키는 DB와 분리하여 권한 0600으로 보관하고, 복구용 키는 /var/backups/finance-board-keys에 별도로 둔다.

## 복구

1. 선택한 스냅샷을 아래의 비공개 복구 작업 디렉터리로 복사하여 무결성, 글 수, 식별 키 지문을 확인한다. 백업 날짜 이후 글·삭제·차단 변경분의 복구 가능 여부를 확인한다.
2. 칼럼 타이머와 백업 타이머, finance-board-web.socket, finance-board.service를 멈춘다. 이미 실행 중인 finance-board-columns.service와 finance-board-backup.service도 종료되었는지 확인한 뒤 복구를 시작한다. 복구에 쓸 사본은 이 과정 전에 별도 위치에 복사해 둔다. 현재 DB 및 같은 이름의 WAL·SHM 파일을 한꺼번에 별도 보호 경로에 보관한다.
3. 확인한 DB 사본을 finance-board 사용자 소유, 0600 권한으로 설치한다. 스냅샷에 대응하는 identity.key를 복구한다. 이전 방식으로 만든 사본에는 로그인 세션과 OTP가 들어 있을 수 있으므로 서비스 기동 전에 sessions와 challenges를 비운다.
4. 서비스·소켓·백업과 칼럼 타이머를 재개한다. 운영자와 작성자가 이메일을 새로 인증하고 권한별 목록·비밀글·차단이 맞는지 확인한다.

## 상담 기록 복구

상담이나 삭제 표식이 포함된 백업으로 기동할 때는 아래 복구 확인을 먼저 마친다. 확인을 기다리는 사본에서는 웹 서비스를 시작하지 않는다. 운영 DB를 교체하기 전에 백업을 **별도의 작업 사본**으로 복사하고, 서비스가 멈춘 시점의 최신 DB를 WAL까지 일관성 있게 보존한다. 해당 DB의 삭제 기록이 최신임을 확인한 뒤 현재 릴리스에서 `python3 maintenance.py restore-consultations <작업사본> <검증된-최신DB>`를 실행한다. 삭제·만료 건은 제외되고 그 밖의 상담과 진행 이력을 복구한다. 삭제 표식은 임의 ID와 시각만 90일간 보관한다. 이전 복구에서 상담을 폐기한 시각도 이후 복구에 이어지므로 더 오래된 사본을 가져와도 해당 시점 이전의 상담은 복원되지 않는다. 최신 삭제 기록을 확보할 수 없으면 `<검증된-최신DB>` 대신 `--discard`를 지정해 상담 내용 없이 게시판을 복구한다. 이 확인은 운영 DB나 원본 백업을 대상으로 실행하지 않는다. 상담 테이블 자체가 없는 도입 전 스냅샷에는 이 단계가 필요하지 않다. 그 사본을 기동하면 새 삭제 기록으로 시작하므로 이전 상담 백업과 조합할 수 없다. 상담 행은 있지만 삭제 표식 기능 도입 전인 구버전 사본은 서비스 기동 전 작업 사본에 `--discard`를 실행한다.

상담이 포함될 수 있는 원본 DB·WAL·SHM과 스냅샷의 임시 복구 사본은 루트 전용 `/var/lib/finance-board-backup/restore-work/<작업 시작 Unix 초>`에 모은다(디렉터리 0700). 복구와 무결성 점검을 끝내면 해당 작업 디렉터리를 즉시 정리하고 백업 타이머를 재개한다. 일별 백업 실행은 중단 후 24시간이 지난 작업 디렉터리를 우선 정리한다.

## 아파트 감사·관리비 칼럼

공식 블로그 financefixer의 공개 RSS를 매일 한국시간 08:20, 12:20, 20:20에 확인한다. 관리비·생활정보 및 회계감사·외부감사에서 아파트 감사나 공동 관리비 주제가 확인된 글을 골라 공개 본문을 게시한다. 표는 행 단위로 옮기고 사진은 원문 링크로 연결한다. 긴 글은 4,000자 안에서 완결된 본문 단락까지 싣는다. 최초 설정 이후 글부터 게시하며 블로그 글번호를 보존해 재시도와 운영자 삭제 뒤에도 중복 게시를 방지한다.

배포 시 시스템 Python의 requests와 bs4가 필요하다. /opt/finance-board/columns/에 column_feed.py와 column_source.py를 함께 설치한다. 웹 릴리스에도 app.py와 column_source.py를 함께 배포하고 finance-board-columns.service와 .timer를 설치한다. systemctl enable --now finance-board-columns.timer로 시작한다. 중단은 systemctl disable --now finance-board-columns.timer로 하고, 발행 대조 기록은 보존한다. 글별 대기 기록은 RSS에서 내려간 뒤에도 재시도에 사용한다.

첫 연재글은 운영자 명의로 별도 게시한 [드라마 〈아파트〉의 178억, 회계사는 어디부터 볼까?](https://board.finance-fixer.net/p/50979288e2687104d1fceab5)이다. 게시물의 관련 자료는 [질문과 공사비 대조표가 있는 사진 칼럼](https://finance-fixer.net/columns/apartment-reserve/)으로 연결된다.
