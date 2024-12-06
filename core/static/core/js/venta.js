// core/static/core/js/ventas.js

document.addEventListener("DOMContentLoaded", function () {
    const numbers = []; // Array para almacenar los números agregados

    const addNumberBtn = document.getElementById("addNumberBtn");
    const numbersTableBody = document.querySelector("#numbersTable tbody");
    const numbersListInput = document.getElementById("numbersList");

    addNumberBtn.addEventListener("click", function () {
        const numberInput = document.getElementById("numero");
        const number = numberInput.value.trim();

        if (number) {
            // Agregar número al array y actualizar el campo oculto
            numbers.push(number);
            updateNumbersListInput();

            // Crear una nueva fila en la tabla para mostrar el número
            const row = document.createElement("tr");
            const numberCell = document.createElement("td");
            const actionCell = document.createElement("td");
            const deleteBtn = document.createElement("button");

            numberCell.textContent = number;
            deleteBtn.textContent = "Eliminar";
            deleteBtn.type = "button";

            // Evento para eliminar un número de la tabla y del array
            deleteBtn.addEventListener("click", function () {
                const rowIndex = row.rowIndex - 1; // Ajustar el índice
                numbers.splice(rowIndex, 1);
                updateNumbersListInput();
                row.remove();
            });

            actionCell.appendChild(deleteBtn);
            row.appendChild(numberCell);
            row.appendChild(actionCell);
            numbersTableBody.appendChild(row);

            // Limpiar el campo de entrada
            numberInput.value = "";
        }
    });

    // Actualizar el campo oculto con los números en formato de cadena
    function updateNumbersListInput() {
        numbersListInput.value = numbers.join(",");
    }
});
