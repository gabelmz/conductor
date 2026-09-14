/* Conductor — Action Queue & Coalescing Manager.
 * Prevents input lag and lazy-load stacking when users click multiple actions rapidly.
 * Cancels/drops stale intermediate tasks and prioritizes the MOST RECENT user action
 * using Last-In-First-Out (LIFO) execution and AbortController request cancellation.
 */
(function actionQueueModule(global) {
  'use strict';

  const activeControllers = new Map();
  let pendingTask = null;
  let isExecuting = false;

  /**
   * Cancel and abort any active in-flight request for an action key.
   */
  function abortInFlight(actionKey) {
    if (activeControllers.has(actionKey)) {
      const controller = activeControllers.get(actionKey);
      try {
        controller.abort();
      } catch (e) {
        /* ignore abort errors */
      }
      activeControllers.delete(actionKey);
    }
  }

  /**
   * Create an AbortController for an action key.
   */
  function createController(actionKey) {
    abortInFlight(actionKey);
    const controller = new AbortController();
    activeControllers.set(actionKey, controller);
    return controller;
  }

  /**
   * Clear all pending queued tasks and abort all in-flight controllers.
   */
  function clearAll() {
    pendingTask = null;
    activeControllers.forEach((controller) => {
      try {
        controller.abort();
      } catch (e) {
        /* ignore */
      }
    });
    activeControllers.clear();
  }

  /**
   * Submit a user action. If another action is already queued, the intermediate
   * action is dropped immediately so the UI jumps straight to the MOST RECENT click.
   *
   * @param {string} actionKey - Category or ID of the action (e.g., 'nav:showView')
   * @param {function(AbortSignal): Promise<any>} taskFn - The async action function
   * @param {object} [options] - Options (e.g. { coalesceGlobal: true })
   */
  async function submit(actionKey, taskFn, options) {
    const opts = options || {};
    const key = opts.coalesceGlobal ? 'global:user_action' : actionKey || 'default';

    // 1. Abort previous in-flight HTTP calls for this action key
    const controller = createController(key);

    // 2. Coalesce/LIFO: Replace pending task with the NEWEST action
    pendingTask = {
      key,
      taskFn,
      signal: controller.signal,
      submittedAt: Date.now(),
    };

    if (isExecuting) {
      // Current task will pick up the updated `pendingTask` once finished
      return;
    }

    // 3. Process task
    isExecuting = true;

    while (pendingTask) {
      const current = pendingTask;
      pendingTask = null; // Consume latest

      try {
        if (!current.signal.aborted) {
          await current.taskFn(current.signal);
        }
      } catch (error) {
        if (error.name !== 'AbortError') {
          console.warn(`[ActionQueue] Action "${current.key}" failed:`, error);
        }
      } finally {
        activeControllers.delete(current.key);
      }
    }

    isExecuting = false;
  }

  /**
   * Helper fetch wrapper that automatically uses AbortController for an action key.
   */
  async function queuedFetch(actionKey, url, fetchOptions) {
    const key = actionKey || url;
    const controller = createController(key);
    const opts = Object.assign({}, fetchOptions || {}, { signal: controller.signal });
    try {
      const response = await fetch(url, opts);
      return response;
    } finally {
      activeControllers.delete(key);
    }
  }

  global.ConductorActionQueue = Object.freeze({
    submit,
    queuedFetch,
    clearAll,
    abortInFlight,
    isExecuting: () => isExecuting,
    hasPending: () => Boolean(pendingTask),
  });
})(window);
