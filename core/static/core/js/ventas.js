// core/static/core/js/ventas.js
(function() {
    'use strict';
  
    // Actualiza el total de la venta
    function updateTotal() {
      const montoFields = document.querySelectorAll('.monto');
      const selectedLotteries = document.querySelectorAll('input[name="loterias"]:checked');
      let total = 0;
      montoFields.forEach(function(input) {
        total += parseFloat(input.value) || 0;
      });
      total *= selectedLotteries.length;
      document.getElementById('total-monto').value = total.toLocaleString('es-CO', {
        style: 'currency',
        currency: 'COP',
        minimumFractionDigits: 0
      });
    }
  
    // Actualiza la visualización de loterías seleccionadas y el texto del botón
    function updateSelectedLotteries() {
      const selected = document.querySelectorAll('input[name="loterias"]:checked');
      const container = document.getElementById('selected-lotteries');
      const button = document.getElementById('lotteryDropdown');
  
      button.textContent = `Seleccionar Loterías (${selected.length})`;
      container.innerHTML = selected.length > 0 ? '<h6 class="mb-2">Loterías seleccionadas:</h6>' : '';
      selected.forEach(function(loteria) {
        const labelText = loteria.parentElement.querySelector('label').textContent.trim();
        const badgeClass = loteria.disabled ? 'bg-secondary' : 'bg-success';
        const span = document.createElement('span');
        span.className = `badge ${badgeClass} me-1 mb-1`;
        span.innerHTML = `${labelText} <i class="bi bi-x-circle ms-1 remove-lottery" style="cursor:pointer;" data-loteria-id="${loteria.id}"></i>`;
        container.appendChild(span);
      });
    }
  
    // Delegación para remover una lotería seleccionada al hacer clic en el icono
    document.getElementById('selected-lotteries').addEventListener('click', function(e) {
      if (e.target.classList.contains('remove-lottery')) {
        const checkbox = document.getElementById(e.target.getAttribute('data-loteria-id'));
        if (checkbox) {
          checkbox.click();
        }
      }
    });
  
    // Asigna eventos a cada checkbox de lotería
    document.querySelectorAll('input[name="loterias"]').forEach(function(checkbox) {
      checkbox.addEventListener('change', function() {
        updateSelectedLotteries();
        updateTotal();
      });
    });
  
    // Delegación de eventos para eliminar filas de la tabla
    document.getElementById('dynamic-table').addEventListener('click', function(e) {
      if (e.target.closest('.remove-row')) {
        e.target.closest('tr').remove();
        updateTotal();
      }
    });
  
    // Asigna listeners a los campos "monto" y "combi" de una fila
    function attachRowListeners(row) {
      const montoInput = row.querySelector('.monto');
      const combiInput = row.querySelector('.combi');
      const numeroInput = row.querySelector('input[name="numero"]');
  
      if (montoInput) {
        montoInput.addEventListener('input', updateTotal);
      }
  
      if (combiInput && numeroInput) {
        // Establece el atributo required según el valor inicial de "combi"
        if (combiInput.value) {
          numeroInput.removeAttribute('required');
        } else {
          numeroInput.setAttribute('required', 'required');
        }
        combiInput.addEventListener('input', function() {
          if (combiInput.value) {
            numeroInput.removeAttribute('required');
          } else {
            numeroInput.setAttribute('required', 'required');
          }
        });
      }
    }
  
    // Al cargar el DOM, asigna eventos a las filas existentes y actualiza el total
    document.addEventListener('DOMContentLoaded', function() {
      document.querySelectorAll('#dynamic-table tbody tr').forEach(function(row) {
        attachRowListeners(row);
      });
      updateTotal();
    });
  
    // Agregar nueva fila a la tabla
    document.getElementById('add-row').addEventListener('click', function() {
      const tbody = document.querySelector('#dynamic-table tbody');
      const newRow = document.createElement('tr');
      newRow.innerHTML = `
        <td><input type="text" name="numero" class="form-control" required></td>
        <td><input type="number" name="combi" class="form-control combi"></td>
        <td><input type="number" name="monto" class="form-control monto" required></td>
        <td>
          <button type="button" class="btn btn-danger btn-sm remove-row">
            <i class="bi bi-trash"></i> Eliminar
          </button>
        </td>
      `;
      tbody.appendChild(newRow);
      attachRowListeners(newRow);
      updateTotal();
    });
  
    // Manejo del envío del formulario con vista previa en modal
    document.getElementById('ventas-form').addEventListener('submit', function(e) {
      e.preventDefault();
      const form = e.target;
      const selectedLotteries = document.querySelectorAll('input[name="loterias"]:checked');
      
      if (selectedLotteries.length === 0) {
        alert("Debe seleccionar al menos una lotería.");
        return;
      }
      
      if (!form.checkValidity()) {
        form.classList.add('was-validated');
        return;
      }
      
      // Preparar detalles de la venta en el modal
      const saleLoteriasList = document.getElementById('saleLoteriasList');
      saleLoteriasList.innerHTML = '';
      selectedLotteries.forEach(function(loteria) {
        const li = document.createElement('li');
        li.textContent = loteria.parentElement.textContent.trim();
        saleLoteriasList.appendChild(li);
      });
  
      const saleDetailsList = document.getElementById('saleDetailsList');
      saleDetailsList.innerHTML = '';
      document.querySelectorAll('#dynamic-table tbody tr').forEach(function(row) {
        const numero = row.querySelector('input[name="numero"]').value;
        const monto = row.querySelector('.monto').value;
        const combi = row.querySelector('.combi').value || 'N/A';
        const tr = document.createElement('tr');
        tr.innerHTML = `<td>${numero}</td><td>${monto}</td><td>${combi}</td>`;
        saleDetailsList.appendChild(tr);
      });
  
      // Calcular total
      let total = 0;
      document.querySelectorAll('.monto').forEach(function(input) {
        total += parseFloat(input.value) || 0;
      });
      total *= selectedLotteries.length;
      document.getElementById('saleTotalAmount').textContent = total.toLocaleString('es-CO', {
        style: 'currency',
        currency: 'COP',
        minimumFractionDigits: 0
      });
  
      // Mostrar modal de detalle de la venta
      const saleDetailModal = new bootstrap.Modal(document.getElementById('saleDetailModal'));
      saleDetailModal.show();
  
      // Agregar evento de confirmación (una sola vez)
      const confirmButton = document.getElementById('confirmSaleButton');
      const newConfirmButton = confirmButton.cloneNode(true);
      confirmButton.parentNode.replaceChild(newConfirmButton, confirmButton);
      newConfirmButton.addEventListener('click', function() {
        const formData = new FormData(form);
        fetch(form.action || window.location.href, {
          method: 'POST',
          headers: {
            'X-CSRFToken': formData.get('csrfmiddlewaretoken')
          },
          body: formData
        })
        .then(response => response.json())
        .then(data => {
          if (data.success) {
            const successModal = new bootstrap.Modal(document.getElementById('successModal'));
            successModal.show();
            document.getElementById('successModal').addEventListener('hidden.bs.modal', function() {
              window.location.reload();
            });
          }
        })
        .catch(error => {
          console.error('Error en el envío:', error);
          alert('Ocurrió un error al enviar la venta.');
        });
      });
    });
  })();
  