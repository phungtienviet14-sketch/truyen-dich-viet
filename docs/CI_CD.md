# CI/CD và phát hành Oracle

## Pipeline hiện tại

`.github/workflows/ci-cd.yml` chạy cho PR/push `main`/`master` và thủ công:

1. Python3.12 + Node22, cài dependencies từ lock có hash, build CSS/JS cục bộ.
2. Ruff kiểm tra lỗi cú pháp/undefined names; pytest unit/integration với DB tạm và credentials giả; **coverage ứng dụng tối thiểu80%**. Không lấy DeepSeek secret production vào test.
3. `pip-audit` kiểm tra dependency runtime. Lỗi audit/test làm dừng phát hành; không dùng `continue-on-error`.
4. Build image thật, chạy container web/worker với volume rỗng riêng, kiểm tra readiness, admin không public, uid không root, `.env` không trong image, heartbeat và restart worker.
5. Chỉ publish GHCR khi nhánh `main`, không phải PR và repository variable `ENABLE_GHCR_PUBLISH=true`. Image mang **full commit SHA**, hỗ trợ AMD64/ARM64; không publish `latest`.

Các bước publish/deploy chưa được chạy ở máy này. Đã bỏ upload mã nguồn lên Hugging Face model repository và ping domain8000; chúng không phải deploy/health gate hợp lệ.

## Dependencies

`requirements.in`: dependencies runtime. `requirements-dev.in`: test/lint/audit/browser; Docker chỉ cài runtime. Lock bao gồm transitive pins + hash, giải cho Python3.12 đa nền tảng:

```bash
uv pip compile requirements.in --python-version 3.12 --universal --generate-hashes --output-file requirements.txt
uv pip compile requirements-dev.in --python-version 3.12 --universal --generate-hashes --output-file requirements-dev.txt
python -m pip install --require-hashes -r requirements-dev.txt
npm ci --ignore-scripts
npm run build
python -m pytest tests --cov=app --cov-report=term-missing --cov-fail-under=80
python -m ruff check --select E9,F63,F7,F82 app scripts tests
python -m pip_audit -r requirements.txt --disable-pip
```

Commit cả `.in` và lock, review thay đổi dependency. Base images và Actions còn dùng version tag; cần kiểm thử cập nhật và ghim digest theo chính sách release nếu yêu cầu tái tạo từng byte. Không đánh đồng lock dependency với image bất biến hoàn toàn.

## Bật phát hành GHCR

Repo hiện cần được đặt trong Git trước khi workflow có thể chạy. Thiết lập branch protection yêu cầu test/container-smoke, review trước merge. Bật variable `ENABLE_GHCR_PUBLISH=true` chỉ khi chủ repo cho phép publish. `GITHUB_TOKEN` có quyền packages:write chỉ ở publish job.

GHCR private cần login trên VM bằng credential chỉ có quyền đọc package; không gửi secret vào lệnh shell/history. Public image chỉ bật sau khi kiểm tra không có secrets hoặc dữ liệu. Artifact runtime chỉ copy `app` và backup script từ allowlist; `.env`, `data`, `.oci`, docs và Git không được gửi vào build context.

## Deploy có phê duyệt

`.github/workflows/deploy-oracle.yml` chỉ có `workflow_dispatch` từ `main`, input full SHA của image đã kiểm thử/publish. Tạo GitHub environment **oracle-production** và cấu hình required reviewers, deployment branch `main`, không cho tự approve nếu gói GitHub hỗ trợ. [GitHub deployment reviews](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/review-deployments).

Nếu tài khoản/repo không hỗ trợ environment protection, giữ workflow chưa cấu hình secrets và chạy script thủ công trên VM sau phê duyệt. File YAML không thể tự bắt buộc reviewer trong repository settings.

Secrets đặt trong environment:

| Tên | Giá trị |
|---|---|
| ORACLE_SSH_HOST | Hostname/IPv4 VM |
| ORACLE_SSH_USER | Tài khoản deploy đã giới hạn |
| ORACLE_SSH_KEY | SSH private key dành riêng cho deploy |
| ORACLE_SSH_KNOWN_HOSTS | Host key đã xác minh qua Console/kênh tin cậy |

Không dùng `StrictHostKeyChecking=no`, không tin `ssh-keyscan` vừa lấy qua cùng đường mạng mà chưa xác minh fingerprint. Không lưu OCI login token hoặc DeepSeek key trong các secrets này. Worker đọc DeepSeek key từ `.env` riêng trên VM.

Workflow dùng SSH đến `/opt/truyen/scripts/deploy_oracle.sh`; bản script/config trên host phải được cập nhật từ release đã review trước. Host tự pull image, snapshot DB, đợi healthcheck. Workflow không tự đăng nhập OCI/tạo VM/sửa DNS. Tài khoản deploy có Docker quyền tương đương root nên dùng SSH key riêng, hạn chế IP hoặc bastion nếu có; runner hosted không có IP cố định thì cân nhắc self-hosted runner trên mạng quản trị thay vì mở SSH rộng.

## Release gate

Không deploy nếu CI chưa xanh, chưa có snapshot/restore drill, credentials chưa xoay sau nghi lộ, hoặc Oracle quota/cost chưa xác nhận. Rollback quy trình trong [Deployment](DEPLOYMENT.md): không tự downgrade schema; script dừng worker khi health thất bại và giữ snapshot. Sau deploy kiểm tra HTTPS, login, read/download và heartbeat; job dịch thật cần ngân sách được cho phép.
