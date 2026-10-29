<script lang="ts">
	import type { FullProfile } from '#lib/types';
	import Icon from './Icon.svelte';
	let { account }: { account: FullProfile } = $props();
	const school = $derived(account.profile);
	function birthDate(value: string | null): string {
		return value
			? new Intl.DateTimeFormat('fr-FR', { dateStyle: 'long', timeZone: 'UTC' }).format(
					new Date(value + 'T00:00:00Z')
				)
			: 'Non renseignée';
	}
	const staffProfile = $derived(
		account.roles.some((role) => ['teacher', 'kholleur', 'admin'].includes(role))
	);
</script>

<div class="school-profile-grid">
	<section class="workspace-panel profile-information profile-identity accent-blue">
		<h2 class="title is-5"><Icon name="profile" />Informations personnelles</h2>
		<dl class="profile-details personal-details">
			<div>
				<dt>Date de naissance</dt>
				<dd>
					{birthDate(school.birth_date)}{#if account.age !== null}
						· {account.age} ans{/if}
				</dd>
			</div>
			<div>
				<dt>Commune</dt>
				<dd>{school.city ? `${school.city} ${school.postal_code ?? ''}` : 'Non renseignée'}</dd>
			</div>
			<div>
				<dt>Téléphone</dt>
				<dd>{school.phone ?? 'Non renseigné'}</dd>
			</div>
			<div>
				<dt>Email</dt>
				<dd>{account.email}</dd>
			</div>
		</dl>
	</section>
	{#if !staffProfile}
		<section class="workspace-panel profile-information accent-violet">
			<h2 class="title is-5"><Icon name="school" />Parcours scolaire</h2>
			<dl class="profile-details">
				<dt>Établissement précédent</dt>
				<dd>{school.previous_school ?? 'Non renseigné'}</dd>
				<dt>Baccalauréat</dt>
				<dd>{school.baccalaureate?.label || 'Non renseigné'}</dd>
				<dt>Année d’obtention</dt>
				<dd>{school.baccalaureate?.year ?? 'Non renseignée'}</dd>
				<dt>Moyenne générale</dt>
				<dd>
					{school.baccalaureate?.overall_grade !== null &&
					school.baccalaureate?.overall_grade !== undefined
						? `${school.baccalaureate.overall_grade} / 20`
						: 'Non renseignée'}
				</dd>
			</dl>
			{#if school.baccalaureate?.subjects.length}<div class="subject-marks mt-4">
					{#each school.baccalaureate.subjects as subject (subject.name)}<div>
							<span>{subject.name}</span><strong
								>{subject.grade !== null ? `${subject.grade} / 20` : '—'}</strong
							>
						</div>{/each}
				</div>{/if}
		</section>
		<section class="workspace-panel profile-information accent-green">
			<h2 class="title is-5"><Icon name="orientation" />Projet d’orientation</h2>
			<p class="orientation-text">
				{school.orientation_project ?? 'Aucun projet renseigné pour le moment.'}
			</p>
		</section>
		<section class="workspace-panel profile-information accent-orange">
			<h2 class="title is-5"><Icon name="adult" />Adulte référent</h2>
			{#if school.reference_adult}<p class="title is-6 mb-2">
					{school.reference_adult.first_name}
					{school.reference_adult.last_name}
				</p>
				<p>{school.reference_adult.phone}</p>{:else}<p class="muted">
					Aucun contact renseigné.
				</p>{/if}
		</section>
	{/if}
</div>
