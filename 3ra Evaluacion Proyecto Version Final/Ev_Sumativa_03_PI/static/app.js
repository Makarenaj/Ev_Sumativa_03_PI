// Mejora progresiva: sin JavaScript el flujo funciona igual (Calcular recarga la página).
// Con JavaScript, Calcular no recarga y la suma de factores se actualiza al editar.
// Las sumas se hacen con enteros (BigInt), nunca con float, para no perder decimales.
(() => {
  const form = document.querySelector(".workflow-form");
  if (!form) return;

  const mensaje = document.querySelector("#calculation-message");
  const firma = document.querySelector("#firma-montos");
  const botonCalcular = document.querySelector("#boton-calcular");
  const botonGrabar = document.querySelector("#boton-grabar");
  const sumaMontos = document.querySelector("#suma-montos");
  const sumaFactores = document.querySelector("#suma-factores");
  const estadoSuma = document.querySelector("#estado-suma");
  const tarjeta = document.querySelector("#tarjeta-suma-factores");
  const DESDE = 8, HASTA = 19;

  // "0,52277431" -> 52277431n (factor x 10^decimales). Devuelve null si no es un número válido.
  const aEntero = (texto, decimales) => {
    const limpio = String(texto).trim().replace(",", ".");
    if (limpio === "") return 0n;
    const partes = new RegExp(`^(\\d+)(?:\\.(\\d{0,${decimales}}))?$`).exec(limpio);
    if (!partes) return null;
    return BigInt(partes[1]) * 10n ** BigInt(decimales) + BigInt((partes[2] || "").padEnd(decimales, "0"));
  };
  const conMiles = (entero) => entero.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  const comoMonto = (centavos) => {
    const dec = (centavos % 100n).toString().padStart(2, "0");
    return conMiles(centavos / 100n) + (dec === "00" ? "" : "," + dec);
  };
  const comoFactor = (valor) => (valor / 100000000n) + "," + (valor % 100000000n).toString().padStart(8, "0");
  const enRango = (input, atributo) => {
    const columna = Number(input.dataset[atributo]);
    return columna >= DESDE && columna <= HASTA;
  };

  const avisar = (texto, esError) => {
    mensaje.textContent = (esError ? "Error: " : "") + texto;
    mensaje.classList.toggle("text-danger", Boolean(esError));
  };

  const actualizarSumaMontos = () => {
    let total = 0n;
    for (const input of form.querySelectorAll("[data-monto]")) {
      if (!enRango(input, "monto")) continue;
      const valor = aEntero(input.value, 2);
      if (valor === null) { sumaMontos.textContent = "—"; return; }
      total += valor;
    }
    sumaMontos.textContent = comoMonto(total);
  };

  const actualizarSumaFactores = () => {
    let total = 0n, hay = false;
    for (const input of form.querySelectorAll("[data-factor]")) {
      if (input.value.trim() !== "" && Number(input.dataset.factor) <= 33) hay = true;
      if (!enRango(input, "factor")) continue;
      const valor = aEntero(input.value, 8);
      if (valor === null) {
        sumaFactores.textContent = "—";
        estadoSuma.textContent = "Hay un factor que no es un número válido.";
        tarjeta.classList.add("summary-error");
        return;
      }
      total += valor;
    }
    const excede = total > 100000000n;
    sumaFactores.textContent = comoFactor(total);
    estadoSuma.textContent = !hay ? "Aún sin calcular." : excede ? "Supera 1: no se puede grabar." : "Cumple: no supera 1.";
    tarjeta.classList.toggle("summary-error", excede);
  };

  // Grabar solo queda disponible con factores calculados sobre los montos actuales.
  const marcarPendiente = (pendiente) => {
    botonGrabar.setAttribute("aria-disabled", pendiente ? "true" : "false");
    botonGrabar.title = pendiente ? "Presiona Calcular antes de grabar" : "";
  };
  marcarPendiente(firma.value === "");

  form.addEventListener("input", (evento) => {
    if (evento.target.matches("[data-monto]")) {
      firma.value = "";
      marcarPendiente(true);
      actualizarSumaMontos();
      avisar("Cambiaste los montos: presiona Calcular para actualizar los factores.", false);
    } else if (evento.target.matches("[data-factor]")) {
      actualizarSumaFactores();
    }
  });

  botonGrabar.addEventListener("click", (evento) => {
    if (botonGrabar.getAttribute("aria-disabled") === "true") {
      evento.preventDefault();
      avisar("Presiona Calcular antes de grabar.", true);
    }
  });

  botonCalcular.addEventListener("click", async (evento) => {
    evento.preventDefault();
    const montos = {}, manuales = {};
    form.querySelectorAll("[data-monto]").forEach((input) => { montos[input.dataset.monto] = input.value || "0"; });
    form.querySelectorAll("[data-factor-manual]").forEach((input) => { manuales[input.dataset.factorManual] = input.value; });
    let respuesta, resultado;
    try {
      respuesta = await fetch("/api/calculo", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": form.querySelector('input[name="csrf_token"]').value,
        },
        body: JSON.stringify({ montos, factores_manuales: manuales }),
      });
      resultado = await respuesta.json();
    } catch {
      form.requestSubmit(botonCalcular);    // sin conexión con la API: cálculo en el servidor
      return;
    }
    if (!respuesta.ok) {
      avisar(resultado.error || "No se pudo calcular. Revisa los montos.", true);
      return;
    }
    Object.entries(resultado.factores).forEach(([columna, factor]) => {
      const input = form.querySelector(`[data-factor="${columna}"]`);
      if (input && Number(columna) <= 33) input.value = factor.replace(".", ",");
    });
    firma.value = resultado.firma;
    marcarPendiente(false);
    actualizarSumaMontos();
    actualizarSumaFactores();
    avisar("Factores calculados. Puedes editarlos antes de grabar.", false);
  });
})();
