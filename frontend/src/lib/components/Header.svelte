<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { canAccess } from '#lib/access';
	import type { User } from '#lib/types';
	import Icon from './Icon.svelte';
	import RoleBadges from './RoleBadges.svelte';
	let { user, establishmentName }: { user: User | null; establishmentName: string } = $props();
	let expanded = $state(false);
	let accountOpen = $state(false);
	let accountArea = $state<HTMLDivElement>();
	let accountButton = $state<HTMLButtonElement>();
	let navigationButton = $state<HTMLButtonElement>();
	let navigation = $state<HTMLElement>();
	const accountId = $props.id();
	const name = $derived(
		[user?.first_name, user?.last_name].filter(Boolean).join(' ') || user?.username || 'Mon compte'
	);
	const initials = $derived(
		name
			.split(/\s+/)
			.slice(0, 2)
			.map((part) => part[0])
			.join('')
	);
	const role = $derived(
		['admin', 'teacher', 'kholleur', 'user'].find((code) => user?.roles.includes(code))
	);
	$effect(() => {
		void page.url.pathname;
		void page.url.search;
		expanded = false;
		accountOpen = false;
	});
	function closeMenus(): void {
		expanded = false;
		accountOpen = false;
	}
	function outside(event: PointerEvent): void {
		if (!(event.target instanceof Node)) return;
		if (!accountArea?.contains(event.target)) accountOpen = false;
		if (!navigation?.contains(event.target)) expanded = false;
	}
	function escape(event: KeyboardEvent): void {
		if (event.key !== 'Escape') return;
		if (accountOpen) {
			accountOpen = false;
			accountButton?.focus();
		} else if (expanded) {
			expanded = false;
			navigationButton?.focus();
		}
	}
</script>

<svelte:window onpointerdown={outside} onkeydown={escape} />
<header class="site-header">
	<nav class="header-nav container" aria-label="Navigation principale" bind:this={navigation}>
		<a
			class="brand header-brand"
			href={resolve('/')}
			onclick={closeMenus}
			aria-label={`${establishmentName}, accueil`}
		>
			<span class="brand-mark" aria-hidden="true"><Icon name="student" size={22} /></span><span
				class="brand-name">{establishmentName}</span
			>
		</a>
		{#if user}
			<div id="main-menu" class="header-links" class:expanded>
				<a
					class="header-link"
					href={resolve('/lessons')}
					aria-current={page.url.pathname === '/lessons' ||
					page.url.pathname.startsWith('/lessons/')
						? 'page'
						: undefined}
					onclick={closeMenus}
					><span class="nav-emblem"><Icon name="book" size={17} /></span><span>Cours</span></a
				>
				{#if canAccess(user, 'staff')}
					<a
						class="header-link"
						href={resolve('/timetable')}
						aria-current={page.url.pathname === '/timetable' ||
						page.url.pathname.startsWith('/timetable/')
							? 'page'
							: undefined}
						onclick={closeMenus}
						><span class="nav-emblem"><Icon name="calendar" size={17} /></span><span
							>Emploi du temps</span
						></a
					>
					<a
						class="header-link"
						href={resolve('/dashboard')}
						aria-current={page.url.pathname === '/dashboard' ||
						page.url.pathname.startsWith('/dashboard/')
							? 'page'
							: undefined}
						onclick={closeMenus}
						><span class="nav-emblem"
							><Icon name={canAccess(user, 'admin') ? 'admin' : 'promotions'} size={17} /></span
						><span>{canAccess(user, 'admin') ? 'Administration' : 'Mes promotions'}</span></a
					>
				{/if}
			</div>
			<div class="header-controls">
				<div
					class="header-account"
					bind:this={accountArea}
					onfocusout={(event) => {
						if (event.relatedTarget instanceof Node && !accountArea?.contains(event.relatedTarget))
							accountOpen = false;
					}}
				>
					<button
						class="account-trigger"
						type="button"
						bind:this={accountButton}
						aria-label={`Menu du compte de ${name}`}
						aria-expanded={accountOpen}
						aria-controls={accountId}
						onclick={() => {
							accountOpen = !accountOpen;
							expanded = false;
						}}
						><span class="account-avatar" data-role={role} aria-hidden="true">{initials}</span><span
							class="account-first-name">{user.first_name || user.username}</span
						><Icon name="chevron" size={12} /></button
					>
					{#if accountOpen}
						<div class="account-dropdown" id={accountId}>
							<div class="account-summary">
								<strong>{name}</strong><span class="account-username">@{user.username}</span
								><RoleBadges roles={user.roles} />
							</div>
							<a
								class="account-action"
								href={resolve('/me')}
								aria-current={page.url.pathname === '/me' ? 'page' : undefined}
								onclick={closeMenus}
								><Icon name="profile" size={17} />Mon profil<Icon name="next" size={12} /></a
							>
							<form method="POST" action={resolve('/logout')} class="account-logout">
								<button type="submit" class="logout-action"
									><Icon name="logout" size={17} />Se déconnecter</button
								>
							</form>
						</div>
					{/if}
				</div>
				<button
					class="navigation-toggle"
					type="button"
					bind:this={navigationButton}
					aria-label={expanded ? 'Fermer le menu de navigation' : 'Afficher le menu de navigation'}
					aria-expanded={expanded}
					aria-controls="main-menu"
					onclick={() => {
						expanded = !expanded;
						accountOpen = false;
					}}><Icon name={expanded ? 'close' : 'menu'} size={20} /></button
				>
			</div>
		{:else}<a class="button is-primary header-login" href={resolve('/login')}
				><Icon name="login" size={16} />Se connecter</a
			>{/if}
	</nav>
</header>

<style>
	.header-nav {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
		align-items: center;
		gap: 1.25rem;
		min-width: 0;
	}
	.header-brand {
		display: flex;
		align-items: center;
		margin: 0;
		justify-self: start;
		text-decoration: none;
		padding-block: 0.4rem;
	}
	.header-brand:hover {
		color: var(--color-primary);
	}
	.header-links {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		padding: 0.35rem;
		border: var(--border-thin);
		border-radius: 1rem;
		background: var(--color-surface);
		flex-shrink: 0;
	}
	.header-link {
		display: flex;
		align-items: center;
		gap: 0.55rem;
		min-height: 44px;
		padding: 0.4rem 0.75rem;
		border-radius: 0.7rem;
		color: var(--color-muted);
		font-size: 0.83rem;
		font-weight: 600;
		transition:
			background-color 160ms ease,
			color 160ms ease;
	}
	.header-link:hover,
	.header-link[aria-current='page'] {
		background: var(--color-soft);
		color: var(--color-primary);
	}
	.header-link[aria-current='page'] {
		box-shadow: inset 0 -2px var(--color-primary);
	}
	.nav-emblem {
		display: grid;
		place-items: center;
		width: 28px;
		height: 28px;
		border-radius: 0.5rem;
		background: var(--color-subtle);
		color: var(--color-primary);
		flex-shrink: 0;
	}
	.header-link:hover .nav-emblem,
	.header-link[aria-current='page'] .nav-emblem {
		background: var(--color-surface);
	}
	.header-controls {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		flex-shrink: 0;
		justify-self: end;
	}
	.header-login {
		grid-column: 3;
		justify-self: end;
	}
	.header-account {
		position: relative;
	}
	.account-trigger,
	.navigation-toggle {
		--action-bg: var(--color-surface);
		--action-hover: var(--color-soft);
		--action-border: var(--color-border);
		--action-hover-shadow: none;
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 0.55rem;
		min-height: 44px;
		padding: 0.35rem 0.6rem;
	}
	.account-trigger[aria-expanded='true'] {
		--action-bg: var(--color-soft);
	}
	.account-avatar {
		--account-tone: var(--color-info);
		--account-soft: var(--color-info-soft);
		display: grid;
		place-items: center;
		width: 32px;
		height: 32px;
		border-radius: 0.65rem;
		background: var(--account-soft);
		color: var(--account-tone);
		font-size: 0.72rem;
		font-weight: 700;
		text-transform: uppercase;
	}
	.account-avatar[data-role='admin'] {
		--account-tone: var(--color-danger);
		--account-soft: var(--color-danger-soft);
	}
	.account-avatar[data-role='teacher'] {
		--account-tone: var(--color-success);
		--account-soft: var(--color-success-soft);
	}
	.account-avatar[data-role='kholleur'] {
		--account-tone: var(--color-violet);
		--account-soft: var(--color-violet-soft);
	}
	.account-first-name {
		max-width: 9rem;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-size: 0.83rem;
	}
	.account-dropdown {
		box-sizing: border-box;
		position: absolute;
		z-index: 30;
		top: calc(100% + 0.65rem);
		right: 0;
		width: min(20rem, calc(100vw - 2rem));
		max-height: calc(100dvh - 6rem);
		overflow-y: auto;
		padding: 0.5rem;
		border: var(--border-thin);
		border-radius: 1rem;
		background: var(--color-surface);
		box-shadow: var(--shadow-panel);
	}
	.account-summary {
		display: grid;
		gap: 0.5rem;
		padding: 0.65rem 0.65rem 0.9rem;
		border-bottom: var(--border-thin);
		margin-bottom: 0.35rem;
		overflow-wrap: anywhere;
	}
	.account-summary strong {
		font-size: 0.92rem;
	}
	.account-username {
		color: var(--color-muted);
		font-size: 0.75rem;
	}
	.account-action,
	.logout-action {
		display: flex;
		align-items: center;
		gap: 0.7rem;
		min-height: 44px;
		width: 100%;
		padding: 0.7rem;
		font-size: 0.83rem;
		border-radius: 0.6rem;
	}
	.account-action {
		color: var(--color-ink);
		box-sizing: border-box;
	}
	.account-action > :global(.app-icon:last-child) {
		margin-left: auto;
	}
	.account-action:hover,
	.account-action[aria-current='page'] {
		color: var(--color-primary);
		background: var(--color-soft);
	}
	.account-logout {
		border-top: var(--border-thin);
		margin-top: 0.35rem;
		padding-top: 0.35rem;
	}
	.logout-action {
		--action-bg: transparent;
		--action-fg: var(--color-danger);
		--action-hover: var(--color-danger-soft);
		--action-border: transparent;
		--action-hover-shadow: none;
		text-align: left;
		font-weight: 500;
	}
	.navigation-toggle {
		display: none;
		width: 44px;
		padding: 0;
	}
	@media (max-width: 1099px) {
		.header-nav {
			display: flex;
			flex-wrap: wrap;
			gap: 0.6rem;
		}
		.header-brand {
			flex: 1;
		}
		.header-links {
			display: none;
			order: 3;
			flex: 1 0 100%;
			box-sizing: border-box;
		}
		.header-links.expanded {
			display: grid;
			grid-template-columns: repeat(3, minmax(0, 1fr));
		}
		.navigation-toggle {
			display: flex;
		}
		.header-link {
			min-width: 0;
		}
		.header-controls {
			margin-left: auto;
		}
	}
	@media (max-width: 600px) {
		.header-nav {
			gap: 0.5rem;
		}
		.header-brand {
			font-size: 1rem;
			gap: 0.5rem;
		}
		.account-first-name {
			display: none;
		}
		.account-trigger {
			padding: 0.3rem 0.4rem;
			gap: 0.3rem;
		}
		.header-links.expanded {
			grid-template-columns: 1fr;
			gap: 0.3rem;
		}
		.header-link {
			min-height: 48px;
		}
		.account-dropdown {
			right: -3rem;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.header-link {
			transition: none;
		}
	}
</style>
