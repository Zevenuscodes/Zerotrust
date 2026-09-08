# Cloud-Based Zero Trust Continuous Authentication System

Behavioral biometrics + AI-based risk analysis for continuous, mid-session authentication — built cloud-native on AWS.

## Abstract

Traditional authentication systems rely on a one-time login process, where users are granted uninterrupted access after successful authentication. This approach poses significant security risks if credentials are compromised during an active session. This project introduces a Cloud-Based Zero Trust Continuous Authentication System that follows the principle of "Never Trust, Always Verify" by continuously validating a user's identity throughout their session.

The system collects behavioral and contextual parameters — typing patterns, mouse movement dynamics, device fingerprint, IP address, and geolocation — and evaluates them in real time through a machine-learning risk engine that produces a dynamic trust score. Based on this score, the system allows continued access, requests multi-factor re-authentication (step-up), or terminates the session.

**Keywords**: Zero Trust Architecture, Continuous Authentication, Behavioral Biometrics, Cloud Computing, Artificial Intelligence, Machine Learning, Cybersecurity, Risk-Based Authentication, Session Security.

## Architecture

```
Internet
   |
[ALB, public subnet, SG: allow 80 from 0.0.0.0/0]
   |
[EC2 in Auto Scaling Group, public subnet, SG: allow app port from ALB SG only]
   - Docker container: FastAPI backend (serves the REST API + the built React SPA)
   - Risk Engine: per-user IsolationForest (behavior) + rule-based context checks
   - IAM instance role: least-privilege access to {this app's S3 bucket, 2 SSM
     parameters, its own CloudWatch log group/metric namespace, SSM Session
     Manager for admin access instead of SSH}
   |
   |--> [RDS PostgreSQL, private subnet, SG: allow 5432 from EC2 SG only]
   |--> [S3 bucket: per-user ML model artifacts, reached via a free Gateway VPC endpoint]
   |--> [CloudWatch: app logs, custom "RiskDecision" metric, 2 alarms -> SNS email]

ECR: holds the built app Docker image, pulled by the EC2 instance on boot.
```

No NAT Gateway is used anywhere (it's an always-on cost with no free tier) — the
app instances sit in a public subnet, guarded by a security group that only lets
the ALB in, with admin access via SSM Session Manager instead of SSH/a bastion.

The security-group chain (`internet -> ALB -> app -> DB`, each hop only allowing
the previous one in) and the IAM role's narrow scope apply the same "never
trust, always verify" principle to the infrastructure itself, not just the
application logic.

### AWS services used, and why (for the cloud computing rubric)

| Service | Role | Why it's here |
|---|---|---|
| **VPC** (public + private subnets, 2 AZs) | Networking | Isolation between the internet-facing tier and the database tier |
| **EC2 + Auto Scaling Group** | Compute | Elastic compute for the app; demonstrates horizontal scaling |
| **Application Load Balancer** | Traffic distribution | Fronts the ASG, health-checks `/health` |
| **RDS (PostgreSQL)** | Managed database | Users, behavior samples, sessions, risk-event audit log |
| **S3** | Object storage | Per-user trained risk-model artifacts (`ModelStore` abstraction) |
| **ECR** | Container registry | Holds the app's Docker image |
| **IAM** (role + least-privilege policy) | Security | Instance can only touch its own bucket/parameters/log group |
| **SSM Parameter Store** (SecureString) | Secrets | JWT signing secret + DB password, fetched at boot, never baked into the image |
| **SSM Session Manager** | Admin access | No SSH keys, no open port 22, no bastion host |
| **CloudWatch** (Logs, custom metric, alarms) | Monitoring | The abstract's "centralized monitoring" claim, backed by a real alarm on risk-engine terminations |
| **SNS** | Alerting | Email notification when an alarm fires |

## Repo layout

```
backend/    FastAPI app: auth, telemetry ingestion, risk engine, REST API
frontend/   React (Vite) app: register/login, live trust-score dashboard
Dockerfile  Multi-stage build: React -> static files served by FastAPI
infra/      Terraform: VPC, EC2/ASG/ALB, RDS, S3, IAM, CloudWatch/SNS
```

## How the trust score is computed

1. **Behavior score (0-100)**: keystroke dwell/flight-time and mouse velocity/
   acceleration features are reduced to an 8-dimensional vector
   (`backend/app/risk_engine.py::featurize`). A per-user `IsolationForest`
   (scikit-learn) is trained on that user's accumulated samples once at least
   5 exist; below that, a normalized distance-from-baseline score is used so
   the very first login still produces a meaningful score.
2. **Context score (0-100)**: rule-based checks against the user's known
   devices/locations (`KnownContext` table) — an unseen device fingerprint
   costs 30 points, an "impossible travel" jump (distance vs. elapsed time
   implying >900 km/h) costs 50.
3. **Combined**: `trust_score = 0.6 * behavior_score + 0.4 * context_score`.
4. **Policy**: `>= 70` allow · `40-69` step-up MFA (a demo 6-digit OTP) ·
   `< 40` terminate the session and log a `risk_events` audit row.

Only telemetry the engine *trusted* (an `allow` decision) is folded back into
the user's behavior history, so a would-be attacker's own telemetry can't
poison the legitimate user's baseline.

## Local development

### Fastest path: Docker Compose

```bash
docker compose up --build
```

This builds the React app, bundles it into the FastAPI image, and starts it
alongside a local Postgres container. Open **http://localhost:8000**.

### Running the pieces separately (hot reload)

```bash
# Postgres only
docker run -d --name zt-postgres -e POSTGRES_USER=ztauth -e POSTGRES_PASSWORD=ztauth \
  -e POSTGRES_DB=ztauth -p 5432:5432 postgres:16-alpine

# Backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # DATABASE_URL already points at localhost:5432
uvicorn app.main:app --reload --port 8000

# Frontend (separate terminal)
cd frontend
cp .env.example .env   # VITE_API_BASE=http://localhost:8000
npm install
npm run dev
```

### Demo script

1. **Register** at `/register`, typing the baseline passphrase shown on the
   page (this seeds your behavior profile) — you'll land on the dashboard
   with trust score 100.
2. **Allow**: keep typing/moving normally in the scratch box — every ~12s a
   telemetry heartbeat is sent and the score should stay high/green.
3. **Step-up**: type noticeably differently (much slower, long pauses) for a
   couple of heartbeats — the score should drop into the orange range and an
   MFA modal appears (demo code: `123456`).
4. **Terminate**: open the dashboard in a different browser (different device
   fingerprint) after logging in there too, or simulate a large,
   fast location jump — the score should crash into the red range and the
   session is killed server-side, even though the JWT hasn't expired yet.

## Deploying to AWS (Terraform)

**This creates real, billed AWS resources — the ALB and RDS instance are not
fully covered by the free tier.** Don't apply this until you're ready to pay
for it, and run `terraform destroy` when you're done demoing.

```bash
# 1. Build and push the image to ECR (get the repo URL first)
cd infra
terraform init
terraform apply -target=module.compute.aws_ecr_repository.app   # creates just the ECR repo first
REPO_URL=$(terraform output -raw ecr_repository_url)
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin "${REPO_URL%%/*}"
docker build -t "$REPO_URL:latest" -f ../Dockerfile ..
docker push "$REPO_URL:latest"

# 2. Configure variables
cp terraform.tfvars.example terraform.tfvars   # set alert_email at minimum

# 3. Deploy everything else
terraform apply

# 4. Open the app
terraform output alb_dns_name

# 5. When you're done — avoid ongoing charges
terraform destroy
```

You'll get an email from SNS to confirm the alarm subscription — accept it to
actually receive alerts.

### Cost awareness

Everything here fits comfortably in typical free-tier limits *except*: the
ALB (hourly + LCU charges) and the RDS instance beyond its 12-month free-tier
window. There's no NAT Gateway (would otherwise be the biggest line item).
Run `terraform destroy` between demo/grading sessions.
