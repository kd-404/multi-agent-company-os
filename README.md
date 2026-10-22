# Loomwell

An AI-run T-shirt company portfolio project: a web app with admin/user login,
a CEO assistant chatbot (RAG-grounded over project/people docs via Azure AI
Foundry), and a Lens-style vision feature (Azure AI Vision) for general image
analysis and T-shirt design originality checks.

Everything here is deployed straight from this repo with no local setup —
every piece below is a Portal click-path.

## 1. Create the Azure resources (Portal)

Do these in order. All in **portal.azure.com**.

### a. Resource Group
`Create a resource` -> search "Resource group" -> name it `loomwell-rg` -> pick a region (use the same region as your existing Foundry project, e.g. UAE North).

### b. Azure Database for PostgreSQL Flexible Server
`Create a resource` -> "Azure Database for PostgreSQL" -> Flexible server ->
- Resource group: `loomwell-rg`
- Server name: `loomwell-db`
- Workload type: Development
- Compute: Burstable, B1ms (cheapest)
- Admin username/password: set and **save these**
- After it deploys: go to the resource -> **Networking** -> enable "Allow public access from any Azure service" (needed so App Service can reach it)
- Go to **Databases** -> add a database named `loomwell`

Your `DATABASE_URL` will be:
```
postgresql://<admin-user>:<password>@loomwell-db.postgres.database.azure.com:5432/loomwell?sslmode=require
```

### c. Azure AI Vision resource (for the Lens feature)
`Create a resource` -> search "Computer Vision" (this is the Azure AI Vision service) ->
- Resource group: `loomwell-rg`
- Name: `loomwell-vision`
- Pricing tier: Free F0 (good enough to start) or S1
- After it deploys -> **Keys and Endpoint** -> copy **Key 1** and the **Endpoint**

### d. Azure AI Foundry — CEO chatbot agent with RAG
You already have `proj-uaenorth`. In the Foundry portal:
1. Go to your project -> **Build** -> **Agents** -> **Create new agent**. Name it `ceo-assistant`.
2. Pick your deployed model (the "smart" tier one) as its base model.
3. Give it instructions like: *"You are Loomwell's CEO assistant. Answer only using the attached knowledge files. Always cite which file an answer came from. If the files don't cover the question, say so plainly instead of guessing."*
4. Under **Tools**, add **File Search**. Create a new vector store, and upload two files to start:
   - `project-status.md` (write a short doc describing what's built so far — Design Studio, phases, etc.)
   - `team.md` (a short doc naming roles — you as founder/CEO, and a line for each department)
5. Save the agent and copy its **Agent ID** (shown in the agent's overview page) and the **project endpoint** (Project overview page, looks like `https://<resource>.services.ai.azure.com/api/projects/<project-name>`).

### e. Azure App Service (hosts the website)
`Create a resource` -> "Web App" ->
- Resource group: `loomwell-rg`
- Name: `loomwell-app` (this becomes `loomwell-app.azurewebsites.net`)
- Publish: Code
- Runtime stack: Python 3.12
- Region: same as the rest
- Plan: Free F1 or Basic B1 to start

## 2. Connect GitHub (Deployment Center) — one-time, no local git needed

On your new `loomwell-app` -> **Deployment Center** (left sidebar) ->
- Source: GitHub
- Authorize GitHub if asked, pick organization `kd-404`, repo `multi-agent-company-os`, branch `main`
- Save. Azure creates a GitHub Actions workflow automatically and deploys on every push to `main`.

## 3. Set the app's environment variables (Portal)

On `loomwell-app` -> **Configuration** -> **Application settings** -> add each of these as a new setting:

| Name | Value |
|---|---|
| `SECRET_KEY` | any long random string |
| `DATABASE_URL` | the PostgreSQL connection string from step 1b |
| `FOUNDRY_PROJECT_ENDPOINT` | from the Foundry project's Overview page ("Project endpoint") |
| `AZURE_SUBSCRIPTION_ID` | your subscription's GUID (Portal -> Subscriptions -> copy "Subscription ID") |
| `AZURE_RESOURCE_GROUP` | the resource group that holds your Foundry project (e.g. the RG for `proj-uaenorth`) |
| `FOUNDRY_PROJECT_NAME` | your Foundry project's name (e.g. `proj-uaenorth`) |
| `FOUNDRY_CEO_AGENT_NAME` | the agent's name in New Foundry (default `ceo-assistant`; only set this if you named it differently) |
| `VISION_ENDPOINT` | from step 1c |
| `VISION_KEY` | from step 1c |

Also set the **Startup Command** under **Configuration -> Stack settings** (not "General settings"):
```
bash startup.sh
```

Save -> the app restarts and picks these up.

## 4. First admin account

Public registration always creates a `user`-role account (by design — see
`app/routes/auth_routes.py`). To get your first admin:
1. Register a normal account through the site.
2. In the PostgreSQL resource -> **Query editor (preview)**, run:
   ```sql
   UPDATE users SET role = 'admin' WHERE email = 'you@example.com';
   ```
3. Log out and back in on the site — you'll now see the Admin panel, from
   which you can create further admins without touching SQL again.

## What's RAG here, specifically

The CEO assistant agent's **File Search** tool (step 1d.4) is the RAG
component: your project-status and team docs are chunked, embedded, and
retrieved per question, with the agent citing the source file rather than
answering from general knowledge. Updating those docs (just re-upload to the
vector store in the Foundry portal) is how you keep the chatbot's answers
current as the Loomwell agent build progresses.
