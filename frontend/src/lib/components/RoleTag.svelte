<script lang="ts">
	import { resolve } from '$app/paths';
	import { roleLabels } from '#lib/roles';
	import Icon from './Icon.svelte';
	let {
		role,
		label,
		userId,
		historical = false
	}: {
		role: string | null;
		label?: string;
		userId?: number;
		historical?: boolean;
	} = $props();
	const roleLabel = $derived(role ? (roleLabels[role] ?? role) : 'Rôle non renseigné');
	const title = $derived(`${roleLabel}${historical ? ' au moment de l’action' : ''}`);
</script>

{#snippet content()}
	<Icon
		name={role === 'admin'
			? 'admin'
			: role === 'teacher'
				? 'teacher'
				: role === 'user'
					? 'student'
					: 'profile'}
		size={14}
	/>
	{label ?? roleLabel}
{/snippet}
{#if userId}
	<a
		class="role-badge"
		class:role-student={role === 'user'}
		class:role-teacher={role === 'teacher'}
		class:role-admin={role === 'admin'}
		class:role-kholleur={role === 'kholleur'}
		href={resolve(`/dashboard/user?id=${userId}`)}
		title={`Voir la fiche · ${title}`}
	>
		{@render content()}
	</a>
{:else}
	<span
		class="role-badge"
		class:role-student={role === 'user'}
		class:role-teacher={role === 'teacher'}
		class:role-admin={role === 'admin'}
		class:role-kholleur={role === 'kholleur'}
		{title}
	>
		{@render content()}
	</span>
{/if}

<style>
	.role-badge {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
		padding: 0.25rem 0.6rem;
		border-radius: 999px;
		font-size: 0.75rem;
		font-weight: 600;
		background: var(--color-soft);
		color: var(--color-ink);
		vertical-align: middle;
		text-decoration: none;
		max-width: 100%;
		overflow-wrap: anywhere;
	}
	.role-student {
		background: var(--color-info-soft);
		color: var(--color-info);
	}
	.role-teacher {
		background: var(--color-success-soft);
		color: var(--color-success);
	}
	.role-admin {
		background: var(--color-danger-soft);
		color: var(--color-danger);
	}
	.role-kholleur {
		background: var(--color-violet-soft);
		color: var(--color-violet);
	}
	a:hover {
		text-decoration: underline;
		box-shadow: inset 0 0 0 1px currentColor;
	}
	a:focus-visible {
		outline: 2px solid currentColor;
		outline-offset: 3px;
	}
</style>
