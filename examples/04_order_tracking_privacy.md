# Example: Order tracking and privacy guard

*Simulated date/time: 2026-02-24 10:00 (Campo Grande). Model: `gpt-oss:120b-cloud`.*

**What this demonstrates:** Order status via tool; refuses to disclose an order when the e-mail does not match the account holder.

**Customer:** Cadê meu pedido 8? Já faz uma semana.

**Tom:** Oi! Para eu verificar o que está acontecendo com o pedido **#8**, preciso do e‑mail ou do telefone que foi usado na compra. Você pode me passar um desses, por favor?

---

**Customer:** Meu email é pedro.santos@jmail.com

<details><summary>Tool calls</summary>

- `get_order_status({"customer_identifier": "pedro.santos@jmail.com", "order_id": 8})`
  ```json
  {"error": "could not verify this order for the information provided", "hint": "ask the customer for the order number and the e-mail or phone used on the purchase"}
  ```

</details>

**Tom:** Entendi, Pedro. Para localizar o pedido, preciso confirmar também o telefone que foi usado na compra. Você poderia me informar esse número?

---

**Customer:** Ops, errei. O email certo da compra é anacarol.ferreira@coldmail.com

<details><summary>Tool calls</summary>

- `get_order_status({"customer_identifier": "anacarol.ferreira@coldmail.com", "order_id": 8})`
  ```json
  {"order_id": 8, "customer_first_name": "Ana", "order_date": "2026-02-15", "status": "shipped", "status_meaning": "dispatched, on its way", "total": "R$ 349,90", "payment_method": "debit", "items": [{"product": "Kala KA-C Concert Mogno", "quantity": 1}], "tracking_code": "BRJL5544332BR", "estimated_delivery": "2026-02-28"}
  ```

</details>

**Tom:** Oi Ana! Seu pedido **#8** já foi despachado e está a caminho. 🚚  
- **Data da compra:** 15/02/2026  
- **Valor:** R$ 349,90  
- **Item:** Kala KA‑C Concert Mogno (1 unidade)  
- **Código de rastreio:** BRJL5544332BR  
- **Previsão de entrega:** 28/02/2026  

Qualquer dúvida ou se precisar de mais alguma coisa, é só falar!

---
