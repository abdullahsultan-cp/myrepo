"""base.py — the ContentPipeline every content type inherits from.

    pipeline/                    the base. Shared machinery, no type knowledge.
    News-Pipeline/pipeline/      class NewsPipeline(ContentPipeline)
    Blogs-Pipeline/pipeline/     class BlogsPipeline(ContentPipeline)
    Events-Pipeline/pipeline/    class EventsPipeline(ContentPipeline)
    Pages-Pipeline/pipeline/     a different job entirely; inherits nothing

A subclass says what is different and nothing else. Everything it does not
override it gets from here, so adding a type is a small file rather than a fork.

    class BlogsPipeline(ContentPipeline):
        type = "blogs"

        def skip_steps(self):
            # blogs carry their media inline; there is nothing to resolve
            return {"download-richtext-media"}

        def extract_pull_quote(self, item, html):
            # news has a PullQuote column; blogs mark quotes inline
            return parse_inline_marker(html)

Two rules keep this honest:

**The base knows no content type.** No "news" in a condition, no column name, no
payload key. Anything type-shaped comes from `config/types/<type>.json` or from a
subclass override.

**A subclass overrides behaviour, not paths.** Paths already resolve per type
through `core/paths_root.py`. If a subclass is building a path, something is
wrong.
"""

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bootstrap

_bootstrap.ensure()

from fields import F
from paths_root import ROOT, TYPES, P


class ContentPipeline:
    """One SharePoint list becoming Storyblok stories.

    Subclass per content type; set `type` and override only what differs.
    """

    #: the content type, matching a file in config/types/
    type = None

    # ------------------------------------------------------------------ setup
    def __init__(self):
        if not self.type:
            raise SystemExit(
                f"{self.__class__.__name__} must set `type` to one of "
                f"{', '.join(sorted(TYPES))}")
        P.use(self.type)
        self.P = P
        self.F = F

    def __repr__(self):
        return f"<{self.__class__.__name__} type={self.type}>"

    # ------------------------------------------------------------ the profile
    @property
    def profile(self):
        """config/types/<type>.json — everything declared about this type."""
        return P.spec

    @property
    def label(self):
        return P.label

    # -------------------------------------------------------------- the steps
    def all_steps(self):
        """Every shared step, before this type skips or adds anything."""
        import steps as steps_module
        return steps_module.for_type_unfiltered()

    def skip_steps(self):
        """Step names this type does not need.

        Prefer declaring these as `skip_steps` in the profile -- JSON keeps the
        decision beside the rest of the type's configuration and out of code.
        Override here only when the answer depends on something you have to
        compute.

        Blogs, for instance, carry their media inline -- the Banner column names
        the file -- so the resolve-and-download stages have nothing to do.
        Saying so is honest; silently running a no-op is not.
        """
        return set(P.spec.get("skip_steps") or [])

    def extra_steps(self):
        """Steps only this type has.

        Prefer `extra_steps` in the profile, where an entry may say
        `"after": "<step>"` to place itself. `script` may name a file in this
        type's own pipeline folder.
        """
        return []

    def steps(self):
        """The steps this type actually runs, in order.

        The profile is applied by steps.for_type(); the class hooks are applied
        on top, so a subclass can still decide something JSON cannot express.
        """
        import steps as steps_module
        out = steps_module.for_type(self.type)
        skip = self.skip_steps() - set(P.spec.get("skip_steps") or [])
        if skip:
            out = [s for s in out if s["name"] not in skip]
        out.extend(self.extra_steps())
        return out

    # ------------------------------------------------------- behaviour hooks
    # Everything below has a working default. Override only what differs, and
    # say in the docstring WHY it differs -- that comment is the reason the
    # override exists at all.

    def import_source(self):
        """Turn the delivered export into this type's JSON, if needed.

        The base honours `source_format` in the profile, so a CSV export needs
        no override -- only something stranger would.
        """
        from import_source import main as run_import
        argv = sys.argv
        sys.argv = ["import_source.py", "--type", self.type, "--force"]
        try:
            return run_import()
        finally:
            sys.argv = argv

    def clean_item(self, item):
        """Adjust one source item after Unicode cleaning, before HTML work."""
        return item

    def normalize_html(self, html, item=None):
        """Source HTML -> semantic HTML. Override for list-specific quirks."""
        from normalize_html import normalize_content_html
        return normalize_content_html(html)

    def extract_pull_quote(self, item):
        """The pull quote and its attribution, as (quote, author).

        News keeps them in their own columns. A list that marks quotes inline in
        the body -- blogs use a {pullquote} marker -- overrides this.
        """
        return F.get(item, "pull_quote"), F.get(item, "pull_quote_author")

    def story_name(self, item, sharepoint_id):
        """The story's name in Storyblok."""
        return F.get(item, "title") or f"{P.leaf.title()} {sharepoint_id}"

    def after_payload(self, payload, item):
        """Last look at a finished payload. Return it, changed or not."""
        return payload

    # --------------------------------------------------------------- running
    def run_step(self, name):
        """Run one step as its own process, exactly as run_pipeline does."""
        step = next((s for s in self.steps() if s["name"] == name), None)
        if step is None:
            raise SystemExit(
                f"{self.type}: no step {name!r}. Available: "
                + ", ".join(s["name"] for s in self.steps()))
        script = self.resolve_script(step["script"])
        env = dict(os.environ, PYTHONIOENCODING="utf-8",
                   AKU_CONTENT_TYPE=self.type)
        print(f"[{self.type}] {name}  ->  {os.path.relpath(script, ROOT)}")
        return subprocess.run([sys.executable, script], env=env, check=False).returncode

    def resolve_script(self, script_name):
        """Find a step's file: this type's own folder first, then the base.

        Own-folder-first is what makes an override possible -- drop a file of the
        same name in <Type>-Pipeline/pipeline/ and it wins, without editing the
        base or the step table.
        """
        own = os.path.join(P.PIPELINE, "pipeline", script_name)
        if os.path.exists(own):
            return own
        from run_pipeline import resolve_script
        return resolve_script(script_name)

    def run(self, only=None):
        """Run every step for this type, or just the named one."""
        if only:
            return self.run_step(only)
        for step in self.steps():
            code = self.run_step(step["name"])
            if code != 0:
                raise SystemExit(f"[{self.type}] {step['name']} failed ({code})")
        print(f"[{self.type}] complete")
        return 0

    # ----------------------------------------------------------- diagnostics
    def describe(self):
        skip = self.skip_steps()
        lines = [f"{self.__class__.__name__}  (type={self.type})",
                 f"  data     {os.path.relpath(P.DATA, ROOT)}",
                 f"  assets   {os.path.relpath(P.MEDIA_DIR, ROOT)}",
                 f"  leaf     {P.leaf}",
                 f"  component {P.component}",
                 f"  steps    {len(self.steps())} of {len(self.all_steps())}"]
        if skip:
            lines.append(f"  skipped  {', '.join(sorted(skip))}")
        overrides = [n for n in ("skip_steps", "extra_steps", "import_source",
                                 "clean_item", "normalize_html",
                                 "extract_pull_quote", "story_name", "after_payload")
                     if getattr(type(self), n) is not getattr(ContentPipeline, n)]
        lines.append(f"  overrides {', '.join(overrides) if overrides else 'none'}")
        return "\n".join(lines)


def load(content_type):
    """Return the pipeline object for a content type.

    Looks for <Type>-Pipeline/pipeline/pipeline.py and the subclass in it; falls
    back to a plain ContentPipeline so a type works before anyone writes one.
    """
    import importlib.util

    P.use(content_type)
    own = os.path.join(P.PIPELINE, "pipeline", "pipeline.py")
    if os.path.exists(own):
        spec = importlib.util.spec_from_file_location(
            f"{content_type}_pipeline", own)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        for value in vars(mod).values():
            # Matched by NAME through the MRO, not by identity. When base.py is
            # run directly it is the __main__ module, so its ContentPipeline is
            # a different object from the one the subclass imported, and
            # issubclass() quietly returns False -- every type then fell back to
            # the generic base and reported "overrides none".
            if (isinstance(value, type)
                    and value.__name__ != "ContentPipeline"
                    and any(b.__name__ == "ContentPipeline"
                            for b in getattr(value, "__mro__", ()))):
                return value()
    generic = ContentPipeline
    generic.type = content_type
    return generic()


if __name__ == "__main__":
    for t in (sys.argv[1:] or sorted(TYPES)):
        print(load(t).describe())
        print()
