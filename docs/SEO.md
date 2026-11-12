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
| WhatsApp CRM for B2C / DTC brands | “Use cases → B2C, DTC and independent stores” |
| WhatsApp private-domain operations / repeat purchase | “Use cases → Private-domain selling, repeat purchase and after-sales” |
| WhatsApp membership / renewal / retention | “Use cases → Membership and retention” |
| WhatsApp CRM for local service businesses | “Use cases → Localized services” |
| WhatsApp after-sales / warranty support | “Use cases → After-sales and warranty support” |
| multi-agent WhatsApp inbox | roles and permissions, FAQ |
| WhatsApp contact ownership / public pool | contacts and public pool section |
| WhatsApp analytics / campaign reporting | analytics section |
| WhatsApp 私域 SCRM / 外贸 WhatsApp 客户管理 | `README.zh-CN.md` |
| WhatsApp 私域复购 / 会员运营 / 本地化服务 / 售后 | `README.zh-CN.md` use cases |

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

## Indexing checklist (the “public but invisible” trap)

A repository can be **public** and still receive no search traffic. The usual cause is not the code; it is a repository setting or missing metadata. Check these in order.

### 1. The search-engine indexing toggle

In the repository:

**Settings → General → Danger Zone → “Allow your repository to be indexed by search engines”**

It must be **checked**. If it is unchecked, Google and Bing are told not to index the repository even though the repository is public. GitHub's own search may still find it, which is why the problem is easy to miss.

Only a repository admin can see and change this setting.

On some GitHub accounts or UI versions, this checkbox is not shown at all. In that case public repositories are indexed by default, and the practical check is the `noindex` test below: if no `noindex` directive appears on the public page, external indexing is allowed.

### 2. Public visibility, not archived, not disabled

- repository visibility is `Public`;
- the repository is not archived;
- the repository is not disabled;
- it is not a fork (forks are excluded from some searches by default).

### 3. Metadata

- About description is filled in;
- homepage is filled in;
- topics are set (up to 20);
- default branch is `main`;
- README is present and readable;
- social preview is uploaded in **Settings → Social preview**.

### 4. External signals

GitHub search and Google ranking are not the same thing. A brand-new repository with no links, stars, forks or mentions can take days or weeks to be crawled, and may never rank for a competitive term without external references.

- link the repository from the product site and help center;
- mention it in relevant articles and community posts;
- do not buy stars or backlinks.

### 5. Verify

Check the public HTML for a `noindex` directive:

```bash
curl -s -A "Mozilla/5.0" https://github.com/OWNER/REPO \
  | grep -iE '<meta[^>]+robots|noindex'
```

If `noindex` appears, the indexing toggle is probably off. If it does not appear, the page is allowed to be indexed; the remaining issue is crawl timing and external links.

Also check:

- `https://github.com/OWNER/REPO` returns 200 without login;
- `https://api.github.com/repos/OWNER/REPO` shows `"visibility": "public"` and `"archived": false`;
- `https://raw.githubusercontent.com/OWNER/REPO/main/README.md` returns 200.

### 6. Search Console and Bing

For a documentation site or GitHub Pages site, submit the sitemap to Google Search Console and Bing Webmaster Tools. A repository page itself cannot be submitted as a sitemap, but external links to it help discovery.

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
