<script lang="ts">
	import { onMount } from 'svelte';
	import { read } from '#lib/dashboard';
	import { teachingRoleEntries } from '#lib/roles';
	import { colorForeground } from '#lib/lessons';
	import type { TeachingTeam } from '#lib/types';
	import Icon from '../Icon.svelte';
	import RoleTag from '../RoleTag.svelte';
	let team = $state<TeachingTeam | null>(null);
	let loading = $state(true);
	let message = $state('');
	const subjects = $derived(
		team?.subjects.map((subject) => ({
			...subject,
			entries: teachingRoleEntries(subject.members)
		})) ?? []
	);
	async function load(): Promise<void> {
		loading = true;
		message = '';
		try {
			team = await read<TeachingTeam>('team');
		} catch (cause) {
			message = (cause as Error).message;
		} finally {
			loading = false;
		}
	}
	onMount(() => {
		void load();
	});
</script>

<section class="workspace-panel">
	<div class="panel-heading">
		<div>
			<p class="eyebrow">Équipe enseignante</p>
			<h2 class="title is-4 mb-2">Les personnes derrière chaque matière.</h2>
			<p class="muted text-small">
				Comptes non archivés, y compris en attente d’activation, affectés aux matières actives. Les
				professeurs précèdent les khôlleurs, puis sont classés par nom.
			</p>
		</div>
		<button class="button is-light" disabled={loading} onclick={load}
			><Icon name="restore" />Actualiser</button
		>
	</div>
	{#if message}<p class="notification is-danger is-light" role="alert">{message}</p>{/if}
	{#if loading}<p class="loading-state" role="status">Chargement de l’équipe…</p>
	{:else if team}
		<p class="team-summary">
			<strong>{team.member_count} membre{team.member_count === 1 ? '' : 's'}</strong><span
				>{team.teacher_count} professeur{team.teacher_count === 1 ? '' : 's'} + {team.kholleur_count}
				khôlleur{team.kholleur_count === 1 ? '' : 's'}</span
			>
		</p>
		<p class="help mb-4">
			Chaque personne est comptée une seule fois par rôle, même si elle enseigne plusieurs matières.
			Une personne ayant les deux rôles figure dans les deux catégories.
		</p>
		{#if subjects.length === 0}<p class="empty-state">Aucune matière à afficher.</p>
		{:else}<div class="team-grid">
				{#each subjects as subject (subject.id)}
					<section
						class="team-subject"
						style={`--subject-color: ${subject.color}`}
						aria-labelledby={`team-subject-${subject.id}`}
					>
						<h3 id={`team-subject-${subject.id}`}>
							<span class="subject-symbol" style:color={colorForeground(subject.color)}
								><Icon name={subject.icon} /></span
							>{subject.name}
						</h3>
						{#if subject.entries.length === 0}<p class="muted text-small">
								Aucun professeur ni khôlleur affecté.
							</p>
						{:else}<ul>
								{#each subject.entries as { member, role } (`${member.id}-${role}`)}<li>
										<RoleTag
											{role}
											label={`${member.first_name} ${member.last_name}`}
											userId={member.id}
										/>
									</li>{/each}
							</ul>{/if}
					</section>
				{/each}
			</div>{/if}
	{/if}
</section>

<style>
	.team-summary {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.6rem 1.25rem;
		padding: 1rem;
		border-radius: 0.8rem;
		background: var(--color-subtle);
	}
	.team-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(min(100%, 320px), 1fr));
		gap: 1rem;
	}
	.team-subject {
		padding: 1.25rem;
		border: 1px solid var(--color-border);
		border-top: 3px solid var(--subject-color);
		border-radius: 0.9rem;
		min-width: 0;
	}
	h3 {
		display: flex;
		align-items: center;
		gap: 0.65rem;
		font-weight: 700;
		font-size: 1.1rem;
		margin-bottom: 1rem;
		overflow-wrap: anywhere;
	}
	.subject-symbol {
		display: inline-flex;
		padding: 0.5rem;
		border-radius: 0.65rem;
		background: var(--subject-color);
	}
	ul {
		list-style: none;
		padding: 0;
		margin: 0;
	}
	li + li {
		border-top: 1px solid var(--color-border);
		margin-top: 0.85rem;
		padding-top: 0.85rem;
	}
</style>
