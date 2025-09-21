// Namespace all sortable extension functions
window.SortableExt = (function () {

    function showOrHidePlaceholders(selectOrDeselect, dataId) {
        const ulOpts = document.getElementById(`${selectOrDeselect}ed_${dataId}`);
        const className = `placeholder-${selectOrDeselect}-opt`;

        if (ulOpts && ulOpts.children.length === 0) {
            ulOpts.classList.add(className);
        } else if (ulOpts) {
            ulOpts.classList.remove(className);
        }
    }

    function createSelected(dataId) {
        const selectContainer = document.getElementById(`selected_${dataId}`);
        Sortable.create(selectContainer, {
            group: dataId,
            animation: 100,
            dataIdAttr: 'data-choice',
            onSort: function () {
                sortLists(dataId);
            }
        });
    }

    function createDeselected(dataId) {
        const deselectContainer = document.getElementById(`deselected_${dataId}`);
        Sortable.create(deselectContainer, {
            group: dataId,
            animation: 100,
            dataIdAttr: 'data-choice',
        });
    }

    function sortLists(dataId) {
        const selectedEl = document.getElementById(`selected_${dataId}`);
        const deselectedEl = document.getElementById(`deselected_${dataId}`);

        showOrHidePlaceholders("select", dataId);
        for (let li of selectedEl.children) {
            li.querySelector(".select").style.display = 'none';
            li.querySelector(".deselect").style.display = 'block';
            li.querySelector("input").setAttribute("name", dataId);
        }

        showOrHidePlaceholders("deselect", dataId);
        for (let li of deselectedEl.children) {
            li.querySelector(".select").style.display = 'block';
            li.querySelector(".deselect").style.display = 'none';
            li.querySelector("input").removeAttribute("name");
        }
    }

    function moveElement(element, direction, dataId) {
        const choiceId = element?.dataset?.choice;
        if (!choiceId) return;

        const container = element.closest('ul');
        const sortableList = Sortable.get(container);

        const order = sortableList.toArray();
        const index = order.indexOf(choiceId);

        if ((index === 0 && direction === 'up') ||
            (index === order.length - 1 && direction === 'down')) {
            return;
        }

        order.splice(index, 1);
        order.splice(direction === 'down' ? index + 1 : index - 1, 0, choiceId);

        sortableList.sort(order, true);
    }

    function arrowButton(event, dataId, listItemSelector) {
        const direction = event.currentTarget.dataset.direction;
        const otherDirection = direction === 'down' ? 'up' : 'down';

        if (event.key === "Enter" || (event.screenX && event.screenY)) {
            const item = event.currentTarget.closest(listItemSelector);
            moveElement(item, direction, dataId);

            // Maintain focus
            const style = window.getComputedStyle(event.currentTarget);
            if (style.display === 'none') {
                const otherButton = event.currentTarget.parentNode.querySelector(`i[data-direction="${otherDirection}"]`);
                otherButton?.focus();
            } else {
                event.currentTarget.focus();
            }
        }
    }

    function addOrRemove(element, oldList, newList, dataId) {
        if (!element.dataset.choice) return;

        // Ensure the element has Bootstrap fade classes
        if (!element.classList.contains('fade')) {
             element.classList.add('fade', 'show'); // start fully visible
        }
         //Force reflow to commit initial state to the browser
         void element.offsetWidth;

        //Add listener for transitional end
        element.addEventListener('transitionend', function handler(e) {
            if (e.propertyName !== 'opacity') return;
            //Now remove from the old list
            oldList.el.removeChild(element);
            element.removeEventListener('transitionend', handler);
            // Move to new parent
            newList.el.appendChild(element);
            // Force reflow to restart transition
             void element.offsetWidth;
            // Fade in
            element.classList.add('show');
            sortLists(dataId);
         });

        //Start fade out
        element.classList.remove('show');
    }

    function addButton(event, dataId, listItemSelector) {
        if (event.key === "Enter" || (event.screenX && event.screenY)) {
            const element = event.currentTarget.closest(listItemSelector);
            const deselectContainer = document.getElementById(`deselected_${dataId}`);
            const selectContainer = document.getElementById(`selected_${dataId}`);
            addOrRemove(element, Sortable.get(deselectContainer), Sortable.get(selectContainer), dataId);
        }
    }

    function removeButton(event, dataId, listItemSelector) {
        if (event.key === "Enter" || (event.screenX && event.screenY)) {
            const element = event.currentTarget.closest(listItemSelector);
            const deselectContainer = document.getElementById(`deselected_${dataId}`);
            const selectContainer = document.getElementById(`selected_${dataId}`);
            addOrRemove(element, Sortable.get(selectContainer), Sortable.get(deselectContainer), dataId);
        }
    }

    function bindButtons(dataId, listItemSelector) {
        function bind(selector, handler) {
            const buttons = document.querySelectorAll(`${selector}[data-id="${dataId}"]`);
            buttons.forEach(btn => {
                btn.addEventListener('click', event => handler(event, dataId, listItemSelector));
                btn.addEventListener('keydown', event => handler(event, dataId, listItemSelector));
            });
        }
        bind('.move-up', arrowButton);
        bind('.move-down', arrowButton);
        bind('.select', addButton);
        bind('.deselect', removeButton);
    }

    function initWidget(id, listItemSelector) {
        createSelected(id);
        createDeselected(id);
        showOrHidePlaceholders("select", id);
        showOrHidePlaceholders("deselect", id);
        bindButtons(id, listItemSelector);
    }

    // Public API
    return {
        initWidget
    };
})();
