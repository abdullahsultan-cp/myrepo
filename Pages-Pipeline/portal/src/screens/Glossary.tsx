import type { Data } from '../lib/store'

export default function Glossary({ d }: { d: Data }) {
  const noTitle = d.plan.folders.filter(f => f.kind === 'folder' && !(f.title || '').trim())
  return (
    <section>
      <h2>What the words mean</h2>
      <p className="lede">Every label used in this app, in plain English.</p>
      <div className="card">
        <dl className="gl">
          <dt>sets permissions</dt>
          <dd>
            A green chip meaning the folder sets its own editing rights. Permissions are purely
            hierarchical: whoever holds one on a folder manages that folder <i>and everything under
            it</i>. An admin at the root manages everything; a team on{' '}
            <code>…/entities/medical-college/departments/anaes</code> manages only that.
          </dd>

          <dt>inherits · X</dt>
          <dd>
            The folder sets no permissions of its own, so whoever manages the nearest folder above
            it manages this one too. There is no such thing as an unowned folder — it is always
            someone, just further up the tree.
          </dd>

          <dt>The odd short names</dt>
          <dd>
            Slugs like <code>bscn</code>, <code>ugme</code> or <code>acss</code> looked like a
            problem until I checked: SharePoint already carries a human title for <b>338 of the
            339</b> of them — &ldquo;BScN Programme&rdquo;, &ldquo;Undergraduate Programme&rdquo;,
            &ldquo;Academic Support Services&rdquo;. They are shown beside the slug throughout, so
            nothing needs renaming. Exactly {noTitle.length} folder has no title at all, and its
            source page 404s.
          </dd>

          <dt>shared</dt>
          <dd>
            A blue chip meaning the folder also belongs to an entity it cannot live under — a
            library branch belonging to a faculty, or a conference belonging to an institute.
          </dd>

          <dt>Entity</dt>
          <dd>
            A faculty, school, institute or centre that AKU itself publishes on{' '}
            <code>aku.edu/academics</code> or <code>aku.edu/research</code>. Anything else is a
            folder, not an entity — that is how the call is made, so it is not my opinion.
          </dd>

          <dt>Region folder</dt>
          <dd>
            A real unit AKU does not publish as an academic unit or a global institute — Cancer
            Centre, Tele-ICU, Ek Saath. It sits directly under its region instead of under{' '}
            <code>entities/</code>.
          </dd>

          <dt>Department</dt>
          <dd>
            A sub-unit of an entity with its own editing team, like Anaesthesiology under Medical
            College. Learned from Pakistan, where each has its own group, and applied to the same
            entity in the other regions.
          </dd>

          <dt>CW / CA group</dt>
          <dd>
            AKU&rsquo;s own naming. <code>CW MC PK</code> is the Content Writer group for Medical
            College Pakistan; <code>CA MC PK</code> is the Content Approver. That pair is why the
            editor/publisher split maps over cleanly.
          </dd>

          <dt>Unique scope</dt>
          <dd>
            A SharePoint folder that sets its own permissions instead of inheriting. Only these rows
            name a real owner — inherited rows repeat the AKU-wide groups and witness nothing.
          </dd>

          <dt>move as is / update first</dt>
          <dd>
            AKU&rsquo;s own call, from their CSV. 480 pages are marked &ldquo;Update and move&rdquo;
            — they need content work before they go.
          </dd>

          <dt>old slug / new slug</dt>
          <dd>
            Paths only, with no domain. The old slug is the live SharePoint path including{' '}
            <code>/Pages/…aspx</code>; the new slug drops that plumbing and the CMS scaffolding
            (<code>regions/</code>, <code>entities/</code>, <code>departments/</code>) so the public
            address stays short. Add your base URL when you deploy.
          </dd>
        </dl>
      </div>
    </section>
  )
}
