# One change needed in the front end: the page address

**Who this is for:** whoever owns the code that turns a Storyblok story's
`full_slug` into the URL a visitor sees on aku.edu.

**What is needed:** one more segment added to the list you already strip.

---

## What you do today

A Pages story's `full_slug` carries structure that exists for editors and
permissions, not for readers. You already remove three segments when building
the public URL:

```
regions        entities        departments
```

So:

```
full_slug   regions/pakistan/entities/medical-college/departments/pathology
public URL  https://www.aku.edu/pakistan/medical-college/pathology
```

## What to add

Strip a **trailing `home`** as well.

```
full_slug   regions/pakistan/entities/medical-college/home
public URL  https://www.aku.edu/pakistan/medical-college
```

## Why

SharePoint serves `X/Pages/home.aspx` **at** `X/`. Every folder's landing page
in the migration is stored as a story called `home` inside that folder, which is
the only way Storyblok can hold it — a folder is itself a story, so the folder
and its landing page cannot share one slug.

Without this change, 465 front doors sit one level below where a reader expects
them, and AKU's own homepage would be at `aku.edu/home` instead of `aku.edu/`.

## The exact rule

Order matters, and there are two subtleties that are easy to get wrong. Both bit
us before this note existed.

```js
const SCAFFOLD = new Set(['regions', 'entities', 'departments']);

function publicPath(fullSlug) {
  let parts = fullSlug.split('/').filter(Boolean);

  // 1. a trailing `home` is the folder's own front door, not a child page
  if (parts.length > 1 && parts[parts.length - 1] === 'home') {
    parts = parts.slice(0, -1);
  }

  // 2. a scaffold segment is invisible only while it is an INTERMEDIATE level.
  //    As the LAST segment it is the thing being addressed and must stay:
  //    `departments` is a real AKU section with its own list page, and
  //    stripping it unconditionally sent that list page to the Medical
  //    College's own front door.
  parts = parts.filter((p, i) => !SCAFFOLD.has(p) || i === parts.length - 1);

  // 3. `global` is not a place a reader knows about
  if (parts[0] === 'global') parts = parts.slice(1);

  // 4. nothing left means the site root — this is the university homepage
  return '/' + parts.join('/');
}
```

## Test cases

Copy these straight into a test. Every one is a real story in the plan.

| `full_slug` | expected public path |
|---|---|
| `regions/global/home` | `/` |
| `regions/pakistan/home` | `/pakistan` |
| `regions/pakistan/entities/medical-college/home` | `/pakistan/medical-college` |
| `regions/pakistan/entities/medical-college/departments/home` | `/pakistan/medical-college/departments` |
| `regions/pakistan/entities/medical-college/departments/pathology/home` | `/pakistan/medical-college/pathology` |
| `regions/pakistan/entities/medical-college/research/home` | `/pakistan/medical-college/research` |
| `regions/pakistan/entities/medical-college/hdp/about-us` | `/pakistan/medical-college/hdp/about-us` |
| `regions/global/about/at-a-glance/appendix-a` | `/about/at-a-glance/appendix-a` |
| `regions/united-kingdom/entities/institute-for-the-study-of-muslim-civilisations/home` | `/united-kingdom/institute-for-the-study-of-muslim-civilisations` |

## Checking your work against ours

`Pages-Pipeline/out/aku-master-pages.csv` has both columns for all 4,591 pages:
`destination_path` is the `full_slug`, `destination_url` is the address it must
produce. If your function disagrees with that column on any row, one of us is
wrong and it is worth a conversation before launch.

## The alternative, if you would rather not touch the front end

Storyblok stories carry a `real_path` field. We can set it per story at upload
time so the CMS itself declares each page's public address and the front end
needs no rule at all. It is more data to keep correct, but it removes the risk
of the two implementations drifting. Say which you prefer.
