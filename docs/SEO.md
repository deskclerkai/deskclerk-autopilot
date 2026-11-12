# Repository SEO and discovery

This is the maintenance standard for the public repository. It keeps the project discoverable without keyword stuffing, fake stars or misleading claims.

## Repository metadata

| Field | Value |
|---|---|
| Name | `deskclerk-autopilot` |
| Description | `Open-source WhatsApp AI operations desk. Bring your own knowledge base.` |
| Homepage | `https://deskclerkai.com` |
| Topics | `whatsapp`, `whatsapp-cloud-api`, `whatsapp-business`, `crm`, `shared-inbox`, `customer-support`, `customer-engagement`, `ai`, `ai-customer-service`, `chatbot`, `self-hosted`, `docker`, `fastapi`, `sqlite`, `python`, `javascript`, `open-source`, `whatsapp-automation`, `multi-agent`, `contact-management` |
| Social preview | `docs/assets/social-preview.png` (upload in repository settings) |
| Default branch | `main` |
| Chinese entry | `README.zh-CN.md` (linked from the English README) |

## README keyword map

Keywords are used where they describe a real feature. They are not repeated in a hidden block.

| Search intent | README section |
|---|---|
| open source WhatsApp CRM | title, first paragraph, FAQ |
| WhatsApp Cloud API CRM | “Official WhatsApp API only”, setup section |
| WhatsApp shared inbox | “WhatsApp shared inbox” feature section |
| self-hosted WhatsApp customer service | quickstart, Docker, architecture |
| WhatsApp AI chatbot with human handoff | “AI reception”, AI capability table |
| WhatsApp AI customer service for business | “Problems it solves”, “Use cases” |
| WhatsApp CRM for export / B2B teams | “Use cases → B2B export and wholesale” |
| WhatsApp after-sales / warranty support | “Use cases → After-sales and warranty support” |
| multi-agent WhatsApp inbox | roles and permissions, FAQ |
| WhatsApp contact ownership / public pool | contacts and public pool section |
| WhatsApp analytics / campaign reporting | analytics section |
| WhatsApp 私域 SCRM / 外贸 WhatsApp 客户管理 | `README.zh-CN.md` |

## Page structure

1. Logo, one-sentence positioning, badges.
2. Screenshots with descriptive alt text.
3. Who it is for / not for.
4. Feature sections with keyword-bearing H3 headings.
5. Official API and security sections for trust.
6. Quickstart, Docker and configuration.
7. FAQ written as real questions.
8. License, trademark and attribution.

## Documentation and canonical content

- Repository `docs/` holds the code-level truth: permissions, pool rules, AI contract, analytics definitions, architecture.
- The DeskClerk help center holds long tutorials, screenshots and buyer-oriented guides.
- Do not copy a full help-center article into the README. Link to it and keep the README as the developer entry point.
- When the same topic exists in both places, the code-level document is canonical for behavior; the help-center article is canonical for step-by-step usage.

## Content cadence

- One tutorial or deep-dive per week while the project is new.
- One release note per version.
- Update the README whenever a headline capability changes.
- Add a FAQ entry when the same question appears in two issues.

## Measurement

| Metric | Where |
|---|---|
| Repository views, clones, referrers | GitHub Insights → Traffic |
| Stars, forks, watchers | GitHub repository |
| Issue and discussion volume | GitHub |
| Documentation page visits | Help-center analytics |
| Signup and key activation | DeskClerk product analytics |

Do not optimize for stars alone. Optimize for clones that become working deployments and for documentation pages that lead to a signup.

## Red lines

- No purchased stars, follows or backlinks.
- No fake “official WhatsApp partner” claims.
- No competitor disparagement.
- No hidden telemetry.
- No keyword blocks or unrelated trending topics.
- No customer data in screenshots or examples.
